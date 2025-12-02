import csv
import logging
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum, Count, Q
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from contracts.models import Contrat
from payments.models import PaiementApporteur
from .forms import (
    ProfileUpdateForm,
    ApporteurCreationForm,
    QuickProfileForm,
    AdminApporteurUpdateForm,
    BulkActionForm,
)
from .forms_onboarding import OnboardingForm
from .models import User
from .models_onboarding import ApporteurOnboarding

logger = logging.getLogger(__name__)
# ==========================================
# VUES PROFIL UTILISATEUR
# ==========================================
@login_required
def profile(request):
    """Profil utilisateur complet (infos + mot de passe)"""
    if request.method == "POST":
        form = ProfileUpdateForm(request.POST, instance=request.user)
        password_form = PasswordChangeForm(request.user, request.POST)

        if "update_profile" in request.POST and form.is_valid():
            form.save()
            messages.success(request, "Profil mis à jour avec succès!")
            return redirect("accounts:profile")

        elif "change_password" in request.POST and password_form.is_valid():
            user = password_form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Mot de passe modifié avec succès!")
            return redirect("accounts:profile")
    else:
        form = ProfileUpdateForm(instance=request.user)
        password_form = PasswordChangeForm(request.user)

    stats = _get_user_stats(request.user)

    return render(
        request,
        "accounts/profile.html",
        {
            "title": "Mon Profil",
            "form": form,
            "password_form": password_form,
            "stats": stats,
            "user": request.user,
        },
    )


@login_required
@require_POST
def quick_edit_profile(request):
    """Mise à jour rapide du profil (HTMX)"""
    form = QuickProfileForm(request.POST, instance=request.user)
    if form.is_valid():
        form.save()
        return JsonResponse(
            {"success": True, "message": "Profil mis à jour avec succès!"}
        )
    return JsonResponse({"success": False, "errors": form.errors})


@login_required
def change_password(request):
    """Changement de mot de passe simple"""
    if request.method == "POST":
        password_form = PasswordChangeForm(request.user, request.POST)
        if password_form.is_valid():
            user = password_form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Mot de passe modifié avec succès!")
            return redirect("accounts:profile")
    else:
        password_form = PasswordChangeForm(request.user)

    return render(
        request,
        "accounts/change_password.html",
        {"title": "Changer le mot de passe", "password_form": password_form},
    )


# ==========================================
# GESTION APPORTEURS (Admin uniquement)
# ==========================================
@staff_member_required
def nouveau_apporteur(request):
    """Création d'un apporteur ou commercial (par staff)."""
    if request.method == "POST":
        form = ApporteurCreationForm(request.POST, current_user=request.user)
        if form.is_valid():
            utilisateur = form.save()
            messages.success(
                request,
                f"Utilisateur {utilisateur.get_full_name()} ({utilisateur.get_role_display()}) créé avec succès !",
            )
            return redirect("accounts:liste_apporteurs")
    else:
        form = ApporteurCreationForm(current_user=request.user)

    return render(
        request,
        "accounts/nouveau_apporteur.html",
        {"title": "Nouvel utilisateur", "form": form},
    )
@staff_member_required
def detail_apporteur(request, pk):
    """Vue détaillée d'un apporteur (ADMIN + COMMERCIAL)"""
    # Optionnel mais plus explicite : seuls ces rôles voient cette vue
    if request.user.role not in ("ADMIN", "COMMERCIAL"):
        messages.error(request, "Vous n'avez pas les droits pour accéder à cette page.")
        return redirect("accounts:profile")

    apporteur = get_object_or_404(User, pk=pk, role="APPORTEUR")
    onboarding = ApporteurOnboarding.objects.filter(user=apporteur).first()
    conditions_html = None
    if onboarding:
        conditions_html = render_to_string(
            "accounts/partials/conditions_apporteur_v1.html",
            {
                "user": apporteur,
                "version": onboarding.version_conditions,
                "today": onboarding.approuve_at or timezone.now(),
            },
            request=request,
        )

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "toggle_status":
            apporteur.is_active = not apporteur.is_active
            apporteur.save()
            messages.success(
                request,
                f"Apporteur {'activé' if apporteur.is_active else 'désactivé'}",
            )

        elif action == "change_grade":
            new_grade = request.POST.get("grade")
            if new_grade in ["PLATINE", "FREEMIUM"]:
                apporteur.grade = new_grade
                apporteur.save()
                messages.success(
                    request, f"Grade modifié en {apporteur.get_grade_display()}"
                )

        elif action == "valider_onboarding" and onboarding:
            if onboarding.est_complet():  # utilise ta méthode helper :contentReference[oaicite:3]{index=3}
                onboarding.status = ApporteurOnboarding.Status.VALIDE
                onboarding.save(update_fields=["status"])
                messages.success(request, "Onboarding validé.")
            else:
                messages.error(
                    request,
                    "Dossier incomplet. CNI recto/verso et signature requis.",
                )

        elif action == "rejeter_onboarding" and onboarding:
            onboarding.status = ApporteurOnboarding.Status.REJETE
            onboarding.save(update_fields=["status"])
            messages.success(request, "Onboarding rejeté.")

        return redirect("accounts:detail_apporteur", pk=pk)

    stats = _get_apporteur_detailed_stats(apporteur)
    derniers_contrats = (
        Contrat.objects.emis_avec_doc()
        .filter(apporteur=apporteur)
        .select_related("client", "vehicule")
        .order_by("-created_at")[:10]
    )
    paiements_attente = (
        PaiementApporteur.objects.filter(
            contrat__apporteur=apporteur, status="EN_ATTENTE"
        )
        .select_related("contrat")
        .order_by("-created_at")[:10]
    )

    return render(
        request,
        "accounts/detail_apporteur.html",
        {
            "title": f"Apporteur - {apporteur.get_full_name()}",
            "apporteur": apporteur,
            "stats": stats,
            "derniers_contrats": derniers_contrats,
            "paiements_attente": paiements_attente,
            "onboarding": onboarding,
            "conditions_html": conditions_html,
        },
    )
@staff_member_required
def edit_apporteur(request, pk):
    """Édition d'un apporteur"""
    apporteur = get_object_or_404(User, pk=pk, role="APPORTEUR")
    if request.method == "POST":
        form = AdminApporteurUpdateForm(request.POST, instance=apporteur)
        if form.is_valid():
            form.save()
            messages.success(
                request, f"{apporteur.get_full_name()} modifié avec succès!"
            )
            return redirect("accounts:detail_apporteur", pk=pk)
    else:
        form = AdminApporteurUpdateForm(instance=apporteur)

    return render(
        request,
        "accounts/edit_apporteur.html",
        {
            "title": f"Modifier - {apporteur.get_full_name()}",
            "form": form,
            "apporteur": apporteur,
        },
    )
@staff_member_required
def liste_apporteurs(request):
    search = request.GET.get("search", "")
    grade = request.GET.get("grade", "")
    status = request.GET.get("status", "")

    apporteurs = User.objects.filter(role="APPORTEUR")

    # Filtres de base
    if search:
        apporteurs = apporteurs.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(username__icontains=search)
            | Q(phone__icontains=search)
        )
    if grade:
        apporteurs = apporteurs.filter(grade=grade)
    if status == "actif":
        apporteurs = apporteurs.filter(is_active=True)
    elif status == "inactif":
        apporteurs = apporteurs.filter(is_active=False)

    # Logique "Contrat Valide" reproduite
    q_valid_status = Q(contrats_apportes__status__in=["EMIS", "ACTIF", "EXPIRE"])
    # Vérification que les fichiers existent (pas null et pas vide)
    q_has_docs = (
        ~Q(contrats_apportes__link_attestation="") &
        Q(contrats_apportes__link_attestation__isnull=False) &
        ~Q(contrats_apportes__link_carte_brune="") &
        Q(contrats_apportes__link_carte_brune__isnull=False)
    )
    filter_valid_contracts = q_valid_status & q_has_docs

    apporteurs = apporteurs.annotate(
        nb_contrats=Count(
            "contrats_apportes",
            filter=filter_valid_contracts,
            distinct=True, # Important pour éviter les doublons dus aux joints
        ),
        # Attention : Sum ne supporte pas distinct=True facilement.
        # On suppose ici une relation 1-1 stricte ou pas de duplication de lignes via d'autres joints
        total_commissions=Sum(
            "contrats_apportes__commission_apporteur",
            filter=filter_valid_contracts,
        ),
        # Sommes sur les paiements (Encaissements)
        # Note: Assurez-vous que related_name='encaissement' est bien sur PaiementApporteur
        montant_attente=Sum(
            "contrats_apportes__encaissement__montant_a_payer",
            filter=Q(contrats_apportes__encaissement__status="EN_ATTENTE"),
        ),
        montant_paye=Sum(
            "contrats_apportes__encaissement__montant_a_payer",
            filter=Q(contrats_apportes__encaissement__status="PAYE"),
        )
    )

    # Tri par défaut : Plus récents d'abord
    paginator = Paginator(apporteurs.order_by("-created_at"), 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "accounts/liste_apporteurs.html",
        {
            "title": "Gestion des Apporteurs",
            "page_obj": page_obj,
            "apporteurs": page_obj, # Pour compatibilité template
            "search": search,
            "grade": grade,
            "status": status,
            "total_count": paginator.count,
        },
    )
@staff_member_required
@require_POST
def delete_apporteur(request, pk):
    """Suppression sécurisée d'un apporteur"""
    apporteur = get_object_or_404(User, pk=pk, role="APPORTEUR")
    if apporteur.contrats_apportes.exists():
        messages.error(
            request, "Impossible de supprimer un apporteur avec des contrats existants."
        )
        return redirect("accounts:detail_apporteur", pk=pk)
    name = apporteur.get_full_name()
    apporteur.delete()
    messages.success(request, f"Apporteur {name} supprimé avec succès!")
    return redirect("accounts:liste_apporteurs")


# ==========================================
# ACTIONS AJAX
# ==========================================
@staff_member_required
@require_POST
def toggle_apporteur_status(request, pk):
    """HTMX: activer/désactiver un apporteur"""
    apporteur = get_object_or_404(User, pk=pk, role="APPORTEUR")
    apporteur.is_active = not apporteur.is_active
    apporteur.save()
    return JsonResponse({"success": True, "is_active": apporteur.is_active})


@staff_member_required
@require_POST
def change_apporteur_grade(request, pk):
    """HTMX: changer grade apporteur"""
    apporteur = get_object_or_404(User, pk=pk, role="APPORTEUR")
    grade = request.POST.get("grade")
    if grade in ["PLATINE", "FREEMIUM"]:
        apporteur.grade = grade
        apporteur.save()
        return JsonResponse(
            {"success": True, "grade_display": apporteur.get_grade_display()}
        )
    return JsonResponse({"success": False, "message": "Grade invalide"})


@staff_member_required
@require_POST
def bulk_actions_apporteurs(request):
    """Actions en lot"""
    form = BulkActionForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"success": False, "message": "Données invalides"})

    action = form.cleaned_data["action"]
    ids = form.cleaned_data["selected_users"]
    apporteurs = User.objects.filter(id__in=ids, role="APPORTEUR")
    count = apporteurs.count()

    if action == "activate":
        apporteurs.update(is_active=True)
        msg = f"{count} activé(s)"
    elif action == "deactivate":
        apporteurs.update(is_active=False)
        msg = f"{count} désactivé(s)"
    elif action == "change_grade_platine":
        apporteurs.update(grade="PLATINE")
        msg = f"{count} passé(s) Platine"
    elif action == "change_grade_freemium":
        apporteurs.update(grade="FREEMIUM")
        msg = f"{count} passé(s) Freemium"
    elif action == "delete":
        if apporteurs.filter(contrats_apportes__isnull=False).exists():
            return JsonResponse(
                {"success": False, "message": "Certains ont des contrats existants"}
            )
        apporteurs.delete()
        msg = f"{count} supprimé(s)"
    else:
        return JsonResponse({"success": False, "message": "Action invalide"})

    return JsonResponse({"success": True, "message": msg})


# ==========================================
# EXPORT / IMPORT
# ==========================================
@staff_member_required
def export_apporteurs(request):
    """Export CSV"""
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="apporteurs.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "Username",
            "Prénom",
            "Nom",
            "Email",
            "Téléphone",
            "Grade",
            "Actif",
            "Création",
            "Adresse",
        ]
    )

    for a in User.objects.filter(role="APPORTEUR").order_by("last_name"):
        writer.writerow(
            [
                a.username,
                a.first_name,
                a.last_name,
                a.email,
                a.phone,
                a.get_grade_display() or "Sans grade",
                "Oui" if a.is_active else "Non",
                a.created_at.strftime("%d/%m/%Y %H:%M"),
                a.address or "",
            ]
        )
    return response
@staff_member_required
def import_apporteurs(request):
    """Import CSV"""
    if request.method == "POST" and request.FILES.get("csv_file"):
        file = request.FILES["csv_file"]
        decoded = file.read().decode("utf-8").splitlines()
        reader = csv.DictReader(decoded)
        created, errors = 0, []

        with transaction.atomic():
            for i, row in enumerate(reader, start=2):
                try:
                    username = row["username"].lower().strip()
                    email = row["email"].lower().strip()
                    phone = "".join(filter(str.isdigit, row["phone"]))
                    if User.objects.filter(
                            Q(username=username) | Q(email=email) | Q(phone=phone)
                    ).exists():
                        raise ValueError("Doublon détecté")
                    User.objects.create_user(
                        username=username,
                        email=email,
                        first_name=row["first_name"].capitalize().strip(),
                        last_name=row["last_name"].capitalize().strip(),
                        phone=phone,
                        address=row.get("address", "").strip(),
                        grade=row.get("grade", "FREEMIUM"),
                        role="APPORTEUR",
                        created_by=request.user,
                    )
                    created += 1
                except Exception as e:
                    errors.append(f"Ligne {i}: {e}")

        if created:
            messages.success(request, f"{created} importé(s)")
        for e in errors[:5]:
            messages.error(request, e)

    return render(
        request, "accounts/import_apporteurs.html", {"title": "Importer Apporteurs"}
    )
# =========================================
# API CHECKS HTMX
# ==========================================
@require_http_methods(["GET"])
def check_username_availability(request):
    username = request.GET.get("username", "").lower().strip()
    exists = User.objects.filter(username=username).exists()
    return JsonResponse(
        {
            "success": not exists,
            "available": not exists,
            "message": "Disponible" if not exists else "Déjà pris",
        }
    )


@require_http_methods(["GET"])
def check_email_availability(request):
    email = request.GET.get("email", "").lower().strip()
    exclude = request.GET.get("exclude_id")
    q = User.objects.filter(email=email)
    if exclude:
        q = q.exclude(id=exclude)
    exists = q.exists()
    return JsonResponse(
        {
            "success": not exists,
            "available": not exists,
            "message": "Disponible" if not exists else "Déjà utilisé",
        }
    )


@require_http_methods(["GET"])
def check_phone_availability(request):
    phone = "".join(filter(str.isdigit, request.GET.get("phone", "")))
    exclude = request.GET.get("exclude_id")
    if len(phone) != 9:
        return JsonResponse(
            {"success": False, "available": False, "message": "Format invalide"}
        )
    q = User.objects.filter(phone=phone)
    if exclude:
        q = q.exclude(id=exclude)
    exists = q.exists()
    return JsonResponse(
        {
            "success": not exists,
            "available": not exists,
            "message": "Disponible" if not exists else "Déjà utilisé",
        }
    )


# ==========================================
# UTILITAIRES STATS (MODIFIÉS pour ne compter que AVEC DOCS)
# ==========================================
def _safe_sum(queryset, field):
    """Retourne une somme numérique, jamais None."""
    return queryset.aggregate(total=Sum(field))["total"] or 0


def _get_user_stats(user):
    """
    Stats pour l'utilisateur connecté.
    CORRECTION : Utilise emis_avec_doc() pour filtrer les contrats.
    """
    today = timezone.now().date()
    first_day = today.replace(day=1)

    if user.role == "APPORTEUR":

        contrats = Contrat.objects.emis_avec_doc().filter(apporteur=user)
        return {
            "total_contrats": contrats.count(),
            "contrats_mois": contrats.filter(created_at__gte=first_day).count(),
            "total_commissions": _safe_sum(contrats, "commission_apporteur"),
            "commissions_mois": _safe_sum(
                contrats.filter(created_at__gte=first_day), "commission_apporteur"
            ),
            "commissions_payees": _safe_sum(
                Contrat.objects.filter(apporteur=user, encaissement__status="PAYE"),
                "commission_apporteur"
            ),
            "commissions_attente": _safe_sum(
                PaiementApporteur.objects.filter(
                    contrat__apporteur=user, status="EN_ATTENTE"
                ),
                "montant_a_payer",
            ),
        }

    if user.role == "ADMIN":
        # CORRECTION : Uniquement contrats avec docs
        contrats = Contrat.objects.emis_avec_doc()
        return {
            "apporteurs_total": User.objects.filter(role="APPORTEUR").count(),
            "apporteurs_actifs": User.objects.filter(
                role="APPORTEUR", is_active=True
            ).count(),
            "contrats_total": contrats.count(),
            "commissions_total": _safe_sum(contrats, "commission_apporteur"),
        }

    if user.role == "COMMERCIAL":
        # CORRECTION : Uniquement contrats avec docs
        contrats = Contrat.objects.emis_avec_doc().filter(apporteur=user)
        return {
            "total_contrats": contrats.count(),
            "contrats_mois": contrats.filter(created_at__gte=first_day).count(),
            "total_primes": _safe_sum(contrats, "prime_ttc"),
        }

    return {}


def _get_apporteur_detailed_stats(apporteur):
    """
    Stats détaillées pour la fiche apporteur (vue admin).
    CORRECTION : Utilise emis_avec_doc() pour filtrer les contrats.
    """
    today = timezone.now().date()
    first_day = today.replace(day=1)

    # CORRECTION : Uniquement contrats avec docs
    contrats_emis = Contrat.objects.emis_avec_doc().filter(apporteur=apporteur)

    return {
        "total_contrats": contrats_emis.count(),
        "contrats_mois": contrats_emis.filter(created_at__gte=first_day).count(),
        "total_primes": _safe_sum(contrats_emis, "prime_ttc"),
        "total_commissions": _safe_sum(contrats_emis, "commission_apporteur"),
        "commissions_payees": _safe_sum(
            PaiementApporteur.objects.filter(
                contrat__apporteur=apporteur, status="PAYE"
            ),
            "montant_a_payer",
        ),
        "commissions_attente": _safe_sum(
            PaiementApporteur.objects.filter(
                contrat__apporteur=apporteur, status="EN_ATTENTE"
            ),
            "montant_a_payer",
        ),
    }


@login_required
def user_stats(request):
    stats = _get_user_stats(request.user)
    return render(
        request,
        "accounts/user_stats.html",
        {
            "title": "Mes Statistiques",
            "stats": stats,
        },
    )


@login_required
def edit_profile(request):
    """Vue dédiée à l'édition du profil utilisateur"""
    if request.method == "POST":
        form = ProfileUpdateForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profil mis à jour avec succès!")
            return redirect("accounts:profile")
    else:
        form = ProfileUpdateForm(instance=request.user)

    return render(
        request,
        "accounts/edit_profile.html",
        {"title": "Modifier mon profil", "form": form, "user": request.user},
    )