import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify
from .forms_onboarding import OnboardingForm
from .models_onboarding import ApporteurOnboarding

logger = logging.getLogger(__name__)


def get_client_ip(request):
    """Récupère l'IP réelle du client."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


@login_required
def apporteur_detail(request):
    """Espace contrat/conditions de l'apporteur"""
    user = request.user

    # 1. Sécurité Rôle
    if not getattr(user, 'is_apporteur', False):
        return redirect("accounts:profile")

    # 2. Récupération
    ob, created = ApporteurOnboarding.objects.get_or_create(user=user)

    is_locked = ob.status in [
        ApporteurOnboarding.Status.VALIDE,
        ApporteurOnboarding.Status.EN_ATTENTE_VALIDATION
    ]

    if request.method == "POST":
        if is_locked:
            messages.error(request, "Dossier en cours de traitement ou déjà validé. Modification impossible.")
            return redirect("accounts:apporteur_detail")

        form = OnboardingForm(request.POST, request.FILES, instance=ob)

        if form.is_valid():
            # Sauvegarde temporaire pour les fichiers
            ob = form.save(commit=False)

            # Audit
            ob.ip_accept = get_client_ip(request)
            ob.ua_accept = request.META.get("HTTP_USER_AGENT", "")

            ob.save()

            # Tentative de soumission
            if ob.soumettre():
                messages.success(request, "Dossier soumis avec succès ! En attente de validation.")
            else:
                # Si incomplet (ex: upload CNI recto mais oubli verso)
                messages.warning(request, "Modifications enregistrées. Dossier incomplet (pièces manquantes).")

            return redirect("accounts:apporteur_detail")
        else:
            messages.error(request, "Veuillez corriger les erreurs ci-dessous.")
    else:
        form = OnboardingForm(instance=ob)

    conditions_html = render_to_string(
        "accounts/partials/conditions_apporteur_v1.html",
        {"user": user, "version": ob.version_conditions, "today": timezone.now()},
        request=request,
    )

    return render(
        request,
        "accounts/apporteur_detail.html",
        {
            "title": "Mon contrat Apporteur",
            "onboarding": ob,
            "form": form,
            "conditions_html": conditions_html,
            "is_locked": is_locked,
        },
    )


@login_required
def contrat_pdf(request):
    """Téléchargement du contrat en PDF."""
    user = request.user

    if not getattr(user, 'is_apporteur', False):
        messages.error(request, "Accès réservé.")
        return redirect("accounts:profile")

    ob = get_object_or_404(ApporteurOnboarding, user=user)

    if not ob.est_complet:
        messages.error(request, "Contrat non finalisé.")
        return redirect("accounts:apporteur_detail")

    context = {
        "user": user,
        "onboarding": ob,
        "date_signature": ob.approuve_at or timezone.now()
    }

    html = render_to_string("accounts/contrat_pdf.html", context, request=request)

    try:
        from weasyprint import HTML
        base_url = request.build_absolute_uri("/")
        pdf = HTML(string=html, base_url=base_url).write_pdf()

        # Nettoyage du nom de fichier pour éviter les bugs d'encodage navigateur
        safe_filename = slugify(f"Contrat-BWHITE-{user.username}-{ob.version_conditions}") + ".pdf"

        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{safe_filename}"'
        return response

    except ImportError:
        logger.error("WeasyPrint manquant.")
        return HttpResponse(html)
    except Exception as e:
        logger.error(f"Erreur PDF: {e}")
        messages.warning(request, "Erreur génération PDF. Voici la version web.")
        return HttpResponse(html)