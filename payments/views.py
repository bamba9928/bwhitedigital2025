# payments/views.py

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import User
from contracts.models import Contrat
from .models import PaiementApporteur
from .forms import DeclarationPaiementForm, ValidationPaiementForm


# -----------------------------
# Utils
# -----------------------------
def _require_apporteur(user) -> bool:
    """
    Vérifie que l'utilisateur est bien un apporteur.
    """
    return user.is_authenticated and getattr(user, "role", None) == "APPORTEUR"


# -----------------------------
# Apporteur : liste de ses paiements
# -----------------------------
@login_required
def mes_paiements(request):
    """
    Liste des encaissements pour l'apporteur connecté.
    Accès interdit aux commerciaux et admins.
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
# Apporteur : déclaration de paiement
# -----------------------------
@login_required
def declarer_paiement(request, contrat_id):
    """
    L’apporteur déclare le règlement du net à reverser pour un contrat donné.

    Conditions:
      - être l’apporteur du contrat (role = APPORTEUR)
      - contrat valide (attestation ou carte brune)
      - encaissement EN_ATTENTE
    """
    if not _require_apporteur(request.user):
        return redirect("accounts:profile")

    contrat = get_object_or_404(
        Contrat.objects.select_related("apporteur", "client"),
        pk=contrat_id,
        apporteur=request.user,
    )

    # Contrat doit être "valide" (émis + docs) — propriété à toi
    if not getattr(contrat, "is_valide", False):
        messages.error(
            request, "Contrat non valide. Attestation ou carte brune manquante."
        )
        return redirect("payments:mes_paiements")

    # Montant attendu côté contrat : on privilégie net_a_reverser
    montant_a_payer_apporteur = getattr(contrat, "net_a_reverser", None)
    if montant_a_payer_apporteur is None:
        # fallback simple si jamais net_a_reverser n'est pas renseigné
        montant_a_payer_apporteur = contrat.prime_ttc - contrat.commission_apporteur

    paiement, created = PaiementApporteur.objects.get_or_create(
        contrat=contrat,
        defaults={
            "montant_a_payer": montant_a_payer_apporteur,
            "status": "EN_ATTENTE",
        },
    )

    # Si déjà créé et en attente, on resynchronise le montant avec le contrat
    if paiement.est_en_attente and paiement.montant_a_payer != montant_a_payer_apporteur:
        paiement.montant_a_payer = montant_a_payer_apporteur
        paiement.save(update_fields=["montant_a_payer"])

    # Bloque les statuts finaux
    if paiement.est_paye:
        messages.info(request, "Ce contrat est déjà marqué comme payé.")
        return redirect("payments:mes_paiements")

    if paiement.est_annule:
        messages.error(request, "Ce paiement a été annulé. Contacte l’administration.")
        return redirect("payments:mes_paiements")

    if request.method == "POST":
        form = DeclarationPaiementForm(request.POST, instance=paiement)
        if form.is_valid():
            paiement = form.save(commit=False)
            # On garde le montant calculé côté serveur
            paiement.montant_a_payer = montant_a_payer_apporteur
            paiement.status = "EN_ATTENTE"
            paiement.save()
            messages.success(
                request,
                "Déclaration soumise. En attente de validation par l’administration.",
            )
            return redirect("payments:mes_paiements")
    else:
        form = DeclarationPaiementForm(instance=paiement)

    return render(
        request,
        "payments/declarer_paiement.html",
        {
            "title": "Déclarer mon paiement",
            "contrat": contrat,
            "paiement": paiement,
            "form": form,
        },
    )


# -----------------------------
# Staff : liste des encaissements
# -----------------------------
@staff_member_required
def liste_encaissements(request):
    """
    Liste des encaissements côté staff (ADMIN + COMMERCIAL).
    Affiche TOUS les encaissements.
    """
    qs = (
        PaiementApporteur.objects.select_related(
            "contrat", "contrat__apporteur", "contrat__client"
        )
        .order_by("-created_at")
    )

    apporteur_id = request.GET.get("apporteur")
    if apporteur_id:
        qs = qs.filter(contrat__apporteur_id=apporteur_id)

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(contrat__numero_police__icontains=q)
            | Q(reference_transaction__icontains=q)
            | Q(contrat__client__prenom__icontains=q)
            | Q(contrat__client__nom__icontains=q)
        )

    # Totaux sur le jeu filtré (recherche + apporteur)
    base_qs = qs

    total_attente = (
        base_qs.filter(status="EN_ATTENTE")
        .aggregate(s=Sum("montant_a_payer"))["s"]
        or 0
    )
    total_paye = (
        base_qs.filter(status="PAYE")
        .aggregate(s=Sum("montant_a_payer"))["s"]
        or 0
    )
    total_annule = (
        base_qs.filter(status="ANNULE")
        .aggregate(s=Sum("montant_a_payer"))["s"]
        or 0
    )

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
# Staff : détail + validation
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
            "methode_paiement": paiement.methode_paiement or "OM",
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
    Marque l'encaissement comme PAYE.
    Autorisé pour ADMIN et COMMERCIAL.
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
