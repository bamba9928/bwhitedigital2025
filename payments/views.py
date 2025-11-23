from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from accounts.models import User
from contracts.models import Contrat
from .models import PaiementApporteur


# -----------------------------
# Forms
# -----------------------------
class DeclarationPaiementForm(forms.ModelForm):
    class Meta:
        model = PaiementApporteur
        fields = ["methode_paiement", "reference_transaction", "numero_compte", "notes"]
        widgets = {
            "methode_paiement": forms.Select(attrs={"class": "form-select"}),
            "reference_transaction": forms.TextInput(attrs={"class": "form-input"}),
            "numero_compte": forms.TextInput(attrs={"class": "form-input"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-textarea"}),
        }

    def clean_reference_transaction(self):
        ref = (self.cleaned_data.get("reference_transaction") or "").strip()
        if not ref:
            raise forms.ValidationError("La référence de transaction est obligatoire.")
        return ref

    def clean_numero_compte(self):
        num = (self.cleaned_data.get("numero_compte") or "").strip()
        if not num:
            raise forms.ValidationError("Le numéro de compte / wallet est obligatoire.")
        return num


class ValidationPaiementForm(forms.Form):
    methode_paiement = forms.ChoiceField(
        choices=PaiementApporteur.METHODE, required=True
    )
    reference_transaction = forms.CharField(max_length=64, required=True)

    def clean_reference_transaction(self):
        ref = (self.cleaned_data.get("reference_transaction") or "").strip()
        if not ref:
            raise forms.ValidationError("Référence obligatoire.")
        return ref


# -----------------------------
# Utils
# -----------------------------
def _require_apporteur(user) -> bool:
    """
    Vérifie que l'utilisateur est bien un apporteur.
    Ne dépend pas d'une propriété optionnelle.
    """
    return user.is_authenticated and getattr(user, "role", None) == "APPORTEUR"


# -----------------------------
# Apporteur: liste et détail
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

    if not getattr(contrat, "is_valide", False):
        messages.error(
            request, "Contrat non valide. Attestation ou carte brune manquante."
        )
        return redirect("payments:mes_paiements")

    paiement, created = PaiementApporteur.objects.get_or_create(
        contrat=contrat,
        defaults={
            "montant_a_payer": contrat.net_a_reverser,
            "status": "EN_ATTENTE",
        },
    )

    # Si déjà créé et en attente, on resynchronise le montant
    if not created and paiement.est_en_attente:
        if paiement.montant_a_payer != contrat.net_a_reverser:
            paiement.montant_a_payer = contrat.net_a_reverser
            paiement.save(update_fields=["montant_a_payer"])

    # Bloque les statuts finaux
    if paiement.est_paye:
        messages.info(request, "Ce contrat est déjà marqué comme payé.")
        return redirect("payments:mes_paiements")

    if paiement.est_annule:
        messages.error(request, "Ce paiement a été annulé. Contacte l’admin.")
        return redirect("payments:mes_paiements")

    if request.method == "POST":
        form = DeclarationPaiementForm(request.POST, instance=paiement)
        if form.is_valid():
            paiement = form.save(commit=False)
            # sécurité: on force l'état attendu côté apporteur
            paiement.status = "EN_ATTENTE"
            paiement.save()
            messages.success(
                request, "Déclaration soumise. En attente de validation admin."
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
# Admin / Staff: liste et validation
# -----------------------------
@staff_member_required
def liste_encaissements(request):
    """
    Liste des encaissements côté staff (ADMIN + COMMERCIAL).
    Les encaissements sont toujours liés à des contrats d'apporteurs.
    """
    qs = (
        PaiementApporteur.objects.select_related(
            "contrat", "contrat__apporteur", "contrat__client"
        )
        .filter(contrat__apporteur__role="APPORTEUR")
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

    # Totaux calculés sur le jeu filtré (apporteur + recherche),
    # mais indépendants du filtre status d'affichage.
    base_qs = qs

    total_attente = (
        base_qs.filter(status="EN_ATTENTE")
        .aggregate(s=Sum("montant_a_payer"))["s"]
        or 0
    )
    total_paye = (
        base_qs.filter(status="PAYE").aggregate(s=Sum("montant_a_payer"))["s"] or 0
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
            "title": "Encaissements apporteurs",
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
    Réservé aux vrais admins.
    """
    paiement = get_object_or_404(PaiementApporteur, pk=paiement_id)

    # garde "vrai admin"
    if not getattr(request.user, "is_true_admin", False):
        messages.error(request, "Seuls les administrateurs peuvent valider un paiement.")
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

    messages.success(request, "Paiement validé.")
    return redirect("payments:detail_encaissement", paiement_id=paiement.id)
