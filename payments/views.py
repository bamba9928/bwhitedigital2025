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
    Si déjà payé : affiche le reçu.
    """
    contrat = get_object_or_404(
        Contrat.objects.select_related("apporteur", "client"), pk=contrat_id
    )

    # Sécurité : appartenance du contrat
    if getattr(request.user, "role", "") == "APPORTEUR" and contrat.apporteur != request.user:
        messages.error(request, "Vous n'avez pas accès à ce contrat.")
        return redirect("accounts:profile")

    # Le contrat doit être émis pour pouvoir payer
    if contrat.status not in ("EMIS", "ACTIF", "EXPIRE"):
        messages.error(
            request,
            "Ce contrat n'est pas encore émis. Vous pourrez payer le net à reverser une fois le contrat émis.",
        )
        return redirect("payments:mes_paiements")

    # Calcul du montant attendu
    montant_attendu = Decimal("0.00")
    prime_ttc = getattr(contrat, "prime_ttc", Decimal("0.00")) or Decimal("0.00")
    com_apporteur = getattr(contrat, "commission_apporteur", Decimal("0.00")) or Decimal("0.00")

    if getattr(request.user, "role", "") == "APPORTEUR":
        # Apporteur : TTC - sa commission
        montant_attendu = prime_ttc - com_apporteur
    elif request.user.is_staff:
        # Admin / Commercial : Totalité du TTC
        montant_attendu = prime_ttc

    montant_attendu = max(montant_attendu, Decimal("0.00"))

    # Création ou récupération du paiement
    paiement, created = PaiementApporteur.objects.get_or_create(
        contrat=contrat,
        defaults={
            "montant_a_payer": montant_attendu,
            "status": "EN_ATTENTE",
        },
    )

    # Mise à jour du montant si nécessaire (et si pas encore payé)
    if not paiement.est_paye and abs(paiement.montant_a_payer - montant_attendu) > Decimal("1.00"):
        paiement.montant_a_payer = montant_attendu
        paiement.save(update_fields=["montant_a_payer"])
    if paiement.est_annule:
        messages.error(
            request,
            "Ce paiement a été annulé. Contactez l'administration.",
        )
        return redirect("payments:mes_paiements")
    if request.method == "POST" and not paiement.est_paye:
        payment_url = bictorys_client.initier_paiement(paiement, request)
        if payment_url:
            return redirect(payment_url)

        messages.error(
            request,
            "Impossible d'initialiser le paiement avec Bictorys. Réessayez plus tard.",
        )

    # Affichage (Formulaire de paiement OU Reçu si payé)
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
@transaction.atomic
def bictorys_callback(request):
    """
    Webhook Bictorys.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    # 1. AUTHENTIFICATION
    expected_secret = getattr(settings, "BICTORYS_WEBHOOK_SECRET", "")
    # On accepte X-API-Key ou X-Api-Key
    received_secret = (
            request.headers.get("X-API-Key")
            or request.headers.get("X-Api-Key")
            or ""
    )

    if not expected_secret or not hmac.compare_digest(received_secret, expected_secret):
        logger.warning(f"Webhook Bictorys rejeté : Clé invalide. Reçu: {received_secret[:5]}...")
        return HttpResponse(status=401)

    # 2. LECTURE SECURISEE
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    # Gestion de l'enveloppe "data" optionnelle
    data = payload.get("data", payload)

    # 3. EXTRACTION
    payment_ref = data.get("paymentReference")
    status = str(data.get("status") or "").lower()

    logger.info(f"Webhook reçu pour {payment_ref} - Statut: {status}")

    # On ignore les échecs, mais on répond 200 pour dire "J'ai bien reçu l'info"
    if status not in ("succeeded", "authorized", "successful"):
        return HttpResponse(status=200)

    # 4. TRAITEMENT DU PAIEMENT
    if not payment_ref or not str(payment_ref).startswith("BWHITE_PAY_"):
        return HttpResponseBadRequest("Référence invalide")

    try:
        pk = int(payment_ref.split("_")[-1])
        # select_for_update verrouille la ligne pendant la transaction
        paiement = PaiementApporteur.objects.select_for_update().get(pk=pk)
    except (ValueError, PaiementApporteur.DoesNotExist):
        return HttpResponse(status=404)

    if paiement.est_paye:
        return HttpResponse(status=200)

    # 5. VALIDATION MONTANT
    try:
        amount_received = Decimal(str(data.get("amount", "0")))
    except:
        return HttpResponseBadRequest("Montant invalide")

    # Tolérance 1 Unité (parfois 5000.00 vs 5000)
    if abs(paiement.montant_a_payer - amount_received) > Decimal("1"):
        logger.error(
            f"Fraude potentielle Webhook! {paiement.pk}: Attendu {paiement.montant_a_payer}, Reçu {amount_received}")
        return HttpResponseBadRequest("Montant incorrect")

    # 6. ENREGISTREMENT
    paiement.marquer_comme_paye(
        methode="BICTORYS",
        reference=str(data.get("id") or data.get("chargeId") or ""),
        numero_client=str(data.get("paymentMeans", "")),
        validated_by=None
    )

    logger.info(f"Paiement {pk} validé via Webhook.")
    return HttpResponse(status=200)