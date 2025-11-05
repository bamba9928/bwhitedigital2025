from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from django.views.generic import TemplateView
from django.http import FileResponse, Http404
from django.contrib.staticfiles import finders
from django.views import View


class ServiceWorkerView(View):
    def get(self, request, *args, **kwargs):
        sw_path = finders.find('sw.js')  # cherche dans /static/
        if not sw_path:
            raise Http404("sw.js introuvable dans les staticfiles")
        return FileResponse(open(sw_path, 'rb'), content_type='application/javascript')

urlpatterns = [
    # Administration
    path('admin-bwhite/', admin.site.urls),

    # Applications
    path('', include('dashboard.urls')),
    path('accounts/', include('accounts.urls')),
    path('contracts/', include('contracts.urls')),
    path('payments/', include('payments.urls')),

    # =========================================================
    # Service Worker, Offline Page, et Manifest (PWA)
    # Servis en tant que templates pour utiliser les tags Django.
    # =========================================================

    path("sw.js", ServiceWorkerView.as_view(), name="sw.js"),

    # 2. Page hors ligne

    path("offline.html", TemplateView.as_view(template_name="offline.html"), name="offline"),

    # 3. Manifest
    # Le fichier doit exister dans templates/manifest.json
    path('manifest.json', TemplateView.as_view(
        template_name='manifest.json',
        content_type='application/manifest+json'
    ), name='manifest'),
]

# =========================================================
# Gestion des fichiers Média et Statiques en mode DEBUG
# =========================================================

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)