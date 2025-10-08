from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve as static_serve
from django.views.generic import TemplateView, RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('dashboard.urls')),
    path('accounts/', include('accounts.urls')),
    path('contracts/', include('contracts.urls')),
    path('payments/', include('payments.urls')),


    # Manifest (servi statiquement)
    path("sw.js", lambda r: static_serve(r, "sw.js", document_root=settings.STATIC_ROOT), name="sw"),  # sert STATIC_ROOT/sw.js à /
    path("offline/", TemplateView.as_view(template_name="offline.html"), name="offline"),
    path('manifest.json', TemplateView.as_view(
        template_name='manifest.json',
        content_type='application/manifest+json'
    ), name='manifest'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)