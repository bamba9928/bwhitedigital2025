from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView

urlpatterns = [
    # Administration
    path("admin-bwhite/", admin.site.urls),

    # Applications
    path("", include("dashboard.urls")),
    path("accounts/", include("accounts.urls")),
    path("contracts/", include("contracts.urls")),
    path("payments/", include("payments.urls")),

    # =========================================================
    # Service Worker, Offline Page, et Manifest (PWA)
    # Servis en tant que templates pour utiliser les tags Django.
    # =========================================================
    path(
        "sw.js",
        TemplateView.as_view(
            template_name="sw.js",
            content_type="application/javascript",
        ),
        name="sw.js",
    ),
    path(
        "offline.html",
        TemplateView.as_view(template_name="offline.html"),
        name="offline",
    ),
    path(
        "manifest.json",
        TemplateView.as_view(
            template_name="manifest.json",
            content_type="application/manifest+json"
        ),
        name="manifest",
    ),

]

# =========================================================
# Gestion des fichiers Média et Statiques en mode DEBUG
# =========================================================

if settings.DEBUG:
    # Cette section gère correctement les fichiers media et statiques
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)