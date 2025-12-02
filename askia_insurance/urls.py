from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from django.views.decorators.cache import never_cache # Import important pour PWA

urlpatterns = [
    # Administration
    path("admin-bwhite/", admin.site.urls),

    # Applications
    path("", include("dashboard.urls")),
    path("accounts/", include("accounts.urls")),
    path("contracts/", include("contracts.urls")),
    path("payments/", include("payments.urls")),

    # =========================================================
    # PWA (Service Worker, Manifest, Offline)
    # =========================================================
    # IMPORTANT : On utilise never_cache pour forcer le navigateur
    # à vérifier les mises à jour du Service Worker à chaque visite.
    path(
        "sw.js",
        never_cache(TemplateView.as_view(
            template_name="sw.js",
            content_type="application/javascript",
        )),
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
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)