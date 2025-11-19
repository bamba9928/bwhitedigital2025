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
    user = request.user
    ob, _ = ApporteurOnboarding.objects.get_or_create(user=user)

    if request.method == "POST":
        form = OnboardingForm(request.POST, request.FILES, instance=ob)

        if form.is_valid():

            ob = form.save(commit=False)

            data_url = request.POST.get("signature_image")
            if data_url and data_url.startswith("data:image/"):
                try:
                    header, b64 = data_url.split(",", 1)
                    ext = "png" if "png" in header else "jpg"
                    ob.signature_image = ContentFile(
                        base64.b64decode(b64),

                        name=f"sig_{user.id}_{int(timezone.now().timestamp())}.{ext}",
                    )
                except Exception as e:
                    logger.error("Échec décodage signature pour user %s: %s", user.id, e)
                    messages.error(request, "La sauvegarde de l'image signature a échoué. Veuillez réessayer.")
                    return redirect("accounts:apporteur_detail")

            ob.a_lu_et_approuve = True
            ob.approuve_at = timezone.now()

            xff = request.META.get("HTTP_X_FORWARDED_FOR")
            ob.ip_accept = (
                xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")
            )
            ob.ua_accept = request.META.get("HTTP_USER_AGENT", "")

            if ob.status not in ("VALIDE", "REJETE"):
                ob.status = "SOUMIS"

            ob.save()
            return redirect("accounts:apporteur_detail")

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
        },
    )
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