import json
import logging
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

    # Sécurité : appartenance du contrat
    if getattr(request.user, "role", "") == "APPORTEUR" and contrat.apporteur != request.user:
        return redirect("accounts:profile")

    # Contrat doit être déjà émis côté métier
    if contrat.status not in ("EMIS", "ACTIF", "EXPIRE"):
        messages.error(
            request,
            "Ce contrat n'est pas encore émis. "
            "Vous pourrez payer le net à reverser une fois le contrat émis.",
        )
        return redirect("payments:mes_paiements")

    # Montant payé par l'apporteur = net à reverser
    montant_attendu = getattr(contrat, "net_a_reverser", None)
    if montant_attendu is None:
        # Fallback de sécurité si net_a_reverser est vide
        montant_attendu = contrat.prime_ttc - contrat.commission_askia

    paiement, created = PaiementApporteur.objects.get_or_create(
        contrat=contrat,
        defaults={
            "montant_a_payer": montant_attendu,
            "status": "EN_ATTENTE",
        },
    )

    # Resync si recalcul sur le contrat
    if paiement.est_en_attente and paiement.montant_a_payer != montant_attendu:
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


# -----------------------------
# Webhook Bictorys
# -----------------------------
@csrf_exempt
def bictorys_callback(request):
    """
    Webhook Bictorys.

    Appelé côté serveur par Bictorys quand le statut d'un paiement change.
    On NE dépend pas de la session de l'utilisateur.
    """
    if request.method != "POST":
        return HttpResponseBadRequest("Méthode non supportée")

    # 1) Vérification de la clé secrète envoyée par Bictorys
    header_secret = (
        request.headers.get("X-Secret-Key")
        or request.META.get("HTTP_X_SECRET_KEY")
        or ""
    )
    expected = getattr(settings, "BICTORYS_WEBHOOK_SECRET", None)

    if not expected or header_secret != expected:
        logger.warning(
            "Webhook Bictorys refusé: secret invalide (reçu=%r)", header_secret
        )
        return HttpResponseForbidden("Invalid signature")

    # 2) Parsing du JSON
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception as exc:
        logger.error("Webhook Bictorys: JSON invalide (%s)", exc)
        return HttpResponseBadRequest("Invalid JSON")

    # Payload typique (simplifié):
    # {
    #   "id": "...",
    #   "amount": 100,
    #   "currency": "XOF",
    #   "status": "succeeded",
    #   "paymentReference": "BWHITE-12",
    #   "pspName": "OM-SN",
    #   "paymentMeans": "0771234567",
    #   "..."
    # }

    status = str(payload.get("status", "")).lower()
    payment_ref = payload.get("paymentReference") or payload.get("payment_reference")

    if not payment_ref:
        logger.error("Webhook Bictorys: paymentReference manquant")
        return HttpResponseBadRequest("Missing paymentReference")

    # 3) Récupérer l'ID du PaiementApporteur à partir de paymentReference
    # Convention: paymentReference = "BWHITE-<paiement_id>"
    paiement_id = None
    try:
        ref_str = str(payment_ref)
        if "-" in ref_str:
            paiement_id = int(ref_str.split("-")[-1])
        else:
            paiement_id = int(ref_str)
    except Exception:
        logger.error(
            "Webhook Bictorys: impossible d'extraire paiement_id depuis %r", payment_ref
        )
        return HttpResponseBadRequest("Invalid paymentReference")

    try:
        paiement = PaiementApporteur.objects.select_related("contrat").get(
            pk=paiement_id
        )
    except PaiementApporteur.DoesNotExist:
        logger.error("Webhook Bictorys: paiement %s introuvable", paiement_id)
        return HttpResponseBadRequest("Unknown payment")

    # 4) Vérifier le montant (recommandé)
    amount = payload.get("amount")
    if amount is not None:
        try:
            amount_dec = Decimal(str(amount))
        except Exception:
            amount_dec = None

        if amount_dec is not None and amount_dec != paiement.montant_a_payer:
            logger.warning(
                "Webhook Bictorys: montant incohérent pour paiement %s "
                "(reçu=%s, attendu=%s)",
                paiement.pk,
                amount_dec,
                paiement.montant_a_payer,
            )
            return HttpResponseBadRequest("Amount mismatch")

    # 5) Si le statut est "succeeded" ou équivalent, on marque comme PAYE
    if status in {"succeeded", "approved", "completed", "authorized"}:
        try:
            paiement.marquer_comme_paye(
                methode=payload.get("pspName", "") or payload.get("paymentChannel", ""),
                reference=str(payload.get("id") or payment_ref),
                numero_client=str(payload.get("paymentMeans") or ""),
                validated_by=None,  # validation système (Bictorys)
            )
            logger.info(
                "Webhook Bictorys: paiement %s marqué PAYE (status=%s)",
                paiement.pk,
                status,
            )
        except Exception as exc:
            logger.exception(
                "Webhook Bictorys: erreur marquer_comme_paye pour paiement %s (%s)",
                paiement.pk,
                exc,
            )
            return HttpResponseBadRequest("Error updating payment")
    else:
        # Autres statuts: on log, on ne change pas le paiement
        logger.info(
            "Webhook Bictorys: statut %s pour paiement %s (aucune MAJ)",
            status,
            paiement.pk,
        )

    # Bictorys attend un 200 pour considérer le webhook comme traité
    return HttpResponse("OK")