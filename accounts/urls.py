from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .views_onboarding import apporteur_detail, contrat_pdf

app_name = 'accounts'

urlpatterns = [
    # Auth
    path('login/',  auth_views.LoginView.as_view(template_name='accounts/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    # Profil
    path('profile/', views.profile, name='profile'),
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('profile/quick-edit/', views.quick_edit_profile, name='quick_edit_profile'),  # POST HTMX
    path('change-password/', views.change_password, name='change_password'),
    path('stats/', views.user_stats, name='user_stats'),

    # Onboarding Apporteur (espace apporteur)
    path('apporteur/detail/', apporteur_detail, name='apporteur_detail'),
    path('apporteur/contrat-pdf/', contrat_pdf, name='contrat_pdf'),

    # Gestion Apporteurs (admin/staff)
    path('apporteurs/', views.liste_apporteurs, name='liste_apporteurs'),
    path('apporteurs/nouveau/', views.nouveau_apporteur, name='nouveau_apporteur'),
    path('apporteurs/<int:pk>/', views.detail_apporteur, name='detail_apporteur'),
    path('apporteurs/<int:pk>/edit/', views.edit_apporteur, name='edit_apporteur'),
    path('apporteurs/<int:pk>/delete/', views.delete_apporteur, name='delete_apporteur'),

    # Actions admin en lot et toggles
    path('apporteurs/bulk-actions/', views.bulk_actions_apporteurs, name='bulk_actions_apporteurs'),
    path('apporteurs/<int:pk>/toggle-status/', views.toggle_apporteur_status, name='toggle_apporteur_status'),
    path('apporteurs/<int:pk>/change-grade/', views.change_apporteur_grade, name='change_apporteur_grade'),

    # Export / Import
    path('apporteurs/export/', views.export_apporteurs, name='export_apporteurs'),
    path('apporteurs/import/', views.import_apporteurs, name='import_apporteurs'),

    # Vérifs AJAX (HTMX) de disponibilité
    path('checks/username/', views.check_username_availability, name='check_username'),
    path('checks/email/', views.check_email_availability, name='check_email'),
    path('checks/phone/', views.check_phone_availability, name='check_phone'),
]
