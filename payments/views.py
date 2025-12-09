import json
import logging
import hmac
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import User
from contracts.models import Contrat
from .models import PaiementApporteur
from .forms import ValidationPaiementForm
from .bictorys_client import bictorys_client

logger = logging.getLogger(__name__)


# -----------------------------
# Utils
# -----------------------------
def _require_apporteur(user) -> bool:
    return user.is_authenticated and getattr(user, "role", None) == "APPORTEUR"


# -----------------------------
# Apporteur : liste de ses paiements
# -----------------------------
@login_required
def mes_paiements(request):
    """
    Liste des encaissements pour l'apporteur connecté.
    """
    if not _require_apporteur(request.user):
        return redirect("accounts:profile")

    qs = (
        PaiementApporteur.objects.select_related(
            "contrat", "contrat__client", "contrat__vehicule"
        )
        .filter(contrat__apporteur=request.user)
        .order_by("-created_at")
    )

    status = (request.GET.get("status") or "").upper()
    if status in {"EN_ATTENTE", "PAYE", "ANNULE"}:
        qs = qs.filter(status=status)

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "payments/mes_paiements.html",
        {
            "title": "Mes encaissements",
            "page_obj": page,
            "paiements": page,
            "filter_status": status,
        },
    )
# -----------------------------
# Apporteur : lancer le paiement (Checkout Bictorys)
# -----------------------------
@login_required
def declarer_paiement(request, contrat_id):
    """
    Récap + bouton 'Payer maintenant' (Checkout Bictorys).

    Règles :
    - l'apporteur ne peut payer que si le contrat est au moins EMIS
      (EMIS / ACTIF / EXPIRE)
    - l'émission Askia n'est PAS bloquée par le paiement
    """
    contrat = get_object_or_404(
        Contrat.objects.select_related("apporteur", "client"), pk=contrat_id
    )

    # Sécurité : appartenance du contrat (un apporteur ne peut payer que ses contrats)
    if getattr(request.user, "role", "") == "APPORTEUR" and contrat.apporteur != request.user:
        messages.error(request, "Vous n'avez pas accès à ce contrat.")
        return redirect("accounts:profile")

    # Contrat doit être déjà émis côté métier
    if contrat.status not in ("EMIS", "ACTIF", "EXPIRE"):
        messages.error(
            request,
            "Ce contrat n'est pas encore émis. "
            "Vous pourrez payer le net à reverser une fois le contrat émis.",
        )
        return redirect("payments:mes_paiements")

    montant_attendu = Decimal("0.00")

    # On sécurise les accès aux champs
    prime_ttc = getattr(contrat, "prime_ttc", Decimal("0.00")) or Decimal("0.00")
    com_apporteur = getattr(contrat, "commission_apporteur", Decimal("0.00")) or Decimal("0.00")

    if getattr(request.user, "role", "") == "APPORTEUR":
        # Apporteur : TTC - sa commission
        montant_attendu = prime_ttc - com_apporteur

    elif request.user.is_staff:
        # Admin / Commercial : doit reverser la totalité du TTC
        montant_attendu = prime_ttc

    # Sécurité anti-négatif
    montant_attendu = max(montant_attendu, Decimal("0.00"))

    # Création ou récupération du paiement
    paiement, created = PaiementApporteur.objects.get_or_create(
        contrat=contrat,
        defaults={
            "montant_a_payer": montant_attendu,
            "status": "EN_ATTENTE",
        },
    )

    if paiement.est_en_attente and abs(paiement.montant_a_payer - montant_attendu) > Decimal("1.00"):
        paiement.montant_a_payer = montant_attendu
        paiement.save(update_fields=["montant_a_payer"])

    if paiement.est_paye:
        messages.info(request, "Ce contrat est déjà payé.")
        return redirect("payments:mes_paiements")

    if paiement.est_annule:
        messages.error(
            request,
            "Ce paiement a été annulé. Contactez l'administration pour plus d'informations.",
        )
        return redirect("payments:mes_paiements")

    # Clic sur "Payer maintenant" → Bictorys
    if request.method == "POST":
        payment_url = bictorys_client.initier_paiement(paiement, request)
        if payment_url:
            return redirect(payment_url)

        messages.error(
            request,
            "Impossible d'initialiser le paiement avec Bictorys. Réessayez plus tard.",
        )

    # Affichage récap + bouton
    return render(
        request,
        "payments/declarer_paiement.html",
        {
            "contrat": contrat,
            "paiement": paiement,
        },
    )

# -----------------------------
# Staff : liste des encaissements
# -----------------------------
@staff_member_required
def liste_encaissements(request):
    """
    Liste des encaissements côté staff (ADMIN + COMMERCIAL).
    """

    qs = (
        PaiementApporteur.objects.select_related(
            "contrat", "contrat__apporteur", "contrat__client"
        )
        .order_by("-created_at")
    )

    # Filtre apporteur
    apporteur_id = request.GET.get("apporteur")
    if apporteur_id:
        qs = qs.filter(contrat__apporteur_id=apporteur_id)

    # Recherche texte
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(contrat__numero_police__icontains=q)
            | Q(reference_transaction__icontains=q)
            | Q(contrat__client__prenom__icontains=q)
            | Q(contrat__client__nom__icontains=q)
        )

    # Totaux sur le jeu filtré (avant filtre de statut)
    base_qs = qs
    total_attente = (
        base_qs.filter(status="EN_ATTENTE").aggregate(s=Sum("montant_a_payer"))["s"] or 0
    )
    total_paye = (
        base_qs.filter(status="PAYE").aggregate(s=Sum("montant_a_payer"))["s"] or 0
    )
    total_annule = (
        base_qs.filter(status="ANNULE").aggregate(s=Sum("montant_a_payer"))["s"] or 0
    )

    # Filtre statut
    st = (request.GET.get("status") or "").upper()
    if st in {"EN_ATTENTE", "PAYE", "ANNULE"}:
        qs = qs.filter(status=st)

    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))

    apporteurs = User.objects.filter(role="APPORTEUR").order_by(
        "first_name", "last_name"
    )

    return render(
        request,
        "payments/liste_encaissements.html",
        {
            "title": "Gestion des Paiements",
            "page_obj": page,
            "paiements": page,
            "total_attente": total_attente,
            "total_paye": total_paye,
            "total_annule": total_annule,
            "apporteurs": apporteurs,
            "filter_status": st,
            "query": q,
            "apporteur_id": apporteur_id,
        },
    )


# -----------------------------
# Staff : détail + validation manuelle
# -----------------------------
@staff_member_required
def detail_encaissement(request, paiement_id):
    """
    Détail d'un encaissement pour le staff (ADMIN + COMMERCIAL).
    """
    paiement = get_object_or_404(
        PaiementApporteur.objects.select_related(
            "contrat", "contrat__apporteur", "contrat__client"
        ),
        pk=paiement_id,
    )

    vform = ValidationPaiementForm(
        initial={
            "methode_paiement": paiement.methode_paiement or "",
            "reference_transaction": paiement.reference_transaction,
        }
    )

    return render(
        request,
        "payments/detail_encaissement.html",
        {
            "title": "Détail encaissement",
            "paiement": paiement,
            "vform": vform,
        },
    )


@staff_member_required
@require_POST
@transaction.atomic
def valider_encaissement(request, paiement_id):
    """
    Marque l'encaissement comme PAYE (régularisation manuelle).
    """
    paiement = get_object_or_404(PaiementApporteur, pk=paiement_id)

    if not request.user.is_staff:
        messages.error(request, "Action non autorisée.")
        return redirect("payments:detail_encaissement", paiement_id=paiement.id)

    if paiement.est_paye:
        messages.info(request, "Déjà validé.")
        return redirect("payments:detail_encaissement", paiement_id=paiement.id)

    if paiement.est_annule:
        messages.error(request, "Ce paiement est annulé et ne peut plus être validé.")
        return redirect("payments:detail_encaissement", paiement_id=paiement.id)

    form = ValidationPaiementForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Formulaire invalide.")
        return redirect("payments:detail_encaissement", paiement_id=paiement.id)

    methode = form.cleaned_data["methode_paiement"]
    reference = form.cleaned_data["reference_transaction"]

    paiement.marquer_comme_paye(
        methode=methode,
        reference=reference,
        validated_by=request.user,
    )

    messages.success(request, "Paiement validé avec succès.")
    return redirect("payments:detail_encaissement", paiement_id=paiement.id)
@csrf_exempt
def bictorys_callback(request):
    """
    Webhook Bictorys.

    Sécurité :
    - Vérifie la signature via X-API-Key (HMAC).
    - Vérifie le montant et la devise avant de valider.
    """

    if request.method != "POST":
        return HttpResponse(status=405)

    # -----------------------------------------------------------
    # 1. SÉCURITÉ : VÉRIFICATION DE LA CLÉ (X-API-Key)
    # -----------------------------------------------------------
    expected_secret = getattr(settings, "BICTORYS_WEBHOOK_SECRET", "")
    if not expected_secret:
        logger.error("BICTORYS_WEBHOOK_SECRET non configurée. Webhook ignoré.")
        return HttpResponse(status=500)

    # On récupère la clé envoyée par Bictorys.
    # On teste plusieurs variantes de casse pour être sûr.
    secret = (
            request.headers.get("X-API-Key")  # Format standard attendu
            or request.headers.get("X-Api-Key")  # Variante
            or request.META.get("HTTP_X_API_KEY")  # Format interne Django/WSGI
            or ""
    )

    # Comparaison cryptographique sécurisée
    if not hmac.compare_digest(secret, expected_secret):
        logger.warning(
            "Webhook Bictorys rejeté : Clé X-API-Key invalide ou manquante."
        )
        return HttpResponse(status=401)

    # -----------------------------------------------------------
    # 2. LECTURE DU PAYLOAD JSON
    # -----------------------------------------------------------
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        logger.error("Webhook Bictorys : JSON invalide.")
        return HttpResponse(status=400)

    # Support du format {"data": {...}} ou {...} direct
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        data = payload["data"]
    else:
        data = payload

    logger.info("Webhook Bictorys reçu (ref: %s)", data.get("paymentReference"))

    # -----------------------------------------------------------
    # 3. EXTRACTION ET VALIDATION DES DONNÉES
    # -----------------------------------------------------------
    status = (data.get("status") or "").lower()
    payment_ref = data.get("paymentReference") or data.get("payment_reference")
    amount = data.get("amount")
    currency = (data.get("currency") or "").upper()

    # Infos transaction pour l'historique
    tx_id = data.get("id") or data.get("chargeId")
    psp_name = data.get("pspName") or data.get("psp_name") or "BICTORYS"
    payment_means = data.get("paymentMeans") or data.get("payment_means") or ""

    if not payment_ref or amount is None or not currency:
        logger.error("Webhook Bictorys : Champs manquants (ref/amount/currency).")
        return HttpResponse(status=400)

    # On ne traite que les succès
    if status not in ("succeeded", "authorized"):
        logger.info("Webhook Bictorys : Statut '%s' ignoré pour %s", status, payment_ref)
        return HttpResponse(status=200)

    # -----------------------------------------------------------
    # 4. RETROUVER LE PAIEMENT EN BASE
    # -----------------------------------------------------------
    # Format attendu : BWHITE_PAY_{ID}
    if not str(payment_ref).startswith("BWHITE_PAY_"):
        logger.error("Webhook Bictorys : Référence inconnue %s", payment_ref)
        return HttpResponse(status=400)

    try:
        paiement_id = int(str(payment_ref).replace("BWHITE_PAY_", ""))
        paiement = PaiementApporteur.objects.get(pk=paiement_id)
    except (ValueError, PaiementApporteur.DoesNotExist):
        logger.error("Webhook Bictorys : Paiement introuvable pour %s", payment_ref)
        return HttpResponse(status=404)

    # Idempotence : Si déjà payé, on s'arrête là (succès)
    if paiement.est_paye:
        return HttpResponse(status=200)

    if paiement.est_annule:
        logger.warning("Webhook Bictorys : Tentative de paiement sur dossier ANNULÉ (#%s)", paiement_id)
        return HttpResponse(status=200)  # On renvoie 200 pour que Bictorys arrête d'envoyer

    # -----------------------------------------------------------
    # 5. VÉRIFICATION DU MONTANT (Anti-Fraude)
    # -----------------------------------------------------------
    try:
        amount_dec = Decimal(str(amount))
    except Exception:
        return HttpResponse(status=400)

    if currency != "XOF":
        logger.error("Webhook Bictorys : Devise incorrecte (%s)", currency)
        return HttpResponse(status=400)

    montant_attendu = paiement.montant_a_payer or Decimal("0")

    # Tolérance de 1 FCFA
    if abs(montant_attendu - amount_dec) > Decimal("1"):
        logger.error(
            "Webhook Bictorys : Montant incorrect. Reçu: %s, Attendu: %s",
            amount_dec, montant_attendu
        )
        return HttpResponse(status=400)

    # -----------------------------------------------------------
    # 6. VALIDATION FINALE
    # -----------------------------------------------------------
    try:
        paiement.marquer_comme_paye(
            methode=psp_name,
            reference=str(tx_id),
            numero_client=str(payment_means),
            validated_by=None  # None = Système
        )
        logger.info("Paiement #%s validé avec succès via Webhook.", paiement_id)
        return HttpResponse(status=200)
    except Exception as e:
        logger.exception("Erreur lors de la validation du paiement #%s", paiement_id)
        return HttpResponse(status=500)