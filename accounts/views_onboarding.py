from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.http import HttpResponse
from django.template.loader import render_to_string
from .models_onboarding import ApporteurOnboarding
from .forms_onboarding import OnboardingForm
import base64
from django.core.files.base import ContentFile
from django.contrib import messages
import logging
logger = logging.getLogger(__name__)


@login_required
def apporteur_detail(request):
    """Espace contrat/conditions de l'apporteur"""
    user = request.user
    if user.role != "APPORTEUR":
        return redirect("accounts:profile")

    ob, _ = ApporteurOnboarding.objects.get_or_create(user=user)

    # Protection statut
    if ob.status in ["VALIDE", "REJETE"] and request.method == "POST":
        messages.error(request, "Onboarding déjà traité par l'admin.")
        return redirect("accounts:apporteur_detail")

    if request.method == "POST":
        form = OnboardingForm(request.POST, request.FILES, instance=ob)
        if not request.POST.get("a_lu_et_approuve"):
            form.add_error(None, "Vous devez accepter le contrat et les conditions.")

        if form.is_valid():
            # Traçage
            ob.approuve_at = timezone.now()
            xff = request.META.get("HTTP_X_FORWARDED_FOR")
            ob.ip_accept = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")
            ob.ua_accept = request.META.get("HTTP_USER_AGENT", "")

            # Statut
            if ob.status not in ("VALIDE", "REJETE"):
                ob.status = "SOUMIS"

            ob.save()
            messages.success(request, "Données soumises avec succès.")
            return redirect("accounts:apporteur_detail")
    else:
        form = OnboardingForm(instance=ob)

    conditions_html = render_to_string(
        "accounts/partials/conditions_apporteur_v1.html",
        {"user": user, "version": ob.version_conditions, "today": timezone.now()},
        request=request,
    )

    return render(request, "accounts/apporteur_detail.html", {
        "title": "Mon contrat Apporteur",
        "onboarding": ob,
        "form": form,
        "conditions_html": conditions_html,
    })
@login_required
def contrat_pdf(request):
    """Téléchargement du contrat en PDF; fallback HTML imprimable."""
    user = request.user
    ob = get_object_or_404(ApporteurOnboarding, user=user)

    html = render_to_string(
        "accounts/contrat_pdf.html",
        {"user": user, "onboarding": ob},
        request=request,
    )

    try:
        from weasyprint import HTML

        pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
        filename = f"Contrat_BWHITE_{user.username}.pdf"
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        logger.warning("Échec génération PDF Weasyprint (fallback HTML): %s", e)
        return HttpResponse(html)