from django.urls import path
from . import views

app_name = 'contracts'

urlpatterns = [
    # Contrats
    path('nouveau/', views.nouveau_contrat, name='nouveau_contrat'),
    path('simuler/', views.simuler_tarif, name='simuler_tarif'),
    path('emettre/', views.emettre_contrat, name='emettre_contrat'),
    path('contrats/', views.liste_contrats, name='liste_contrats'),
    path('contrats/<int:pk>/', views.detail_contrat, name='detail_contrat'),
    path('contrats/<int:pk>/documents/', views.telecharger_documents, name='telecharger_documents'),
    path("contrats/<int:pk>/annuler/", views.annuler_contrat, name="annuler_contrat"),
    path("echeances/aujourdhui/", views.echeances_aujourdhui, name="echeances_aujourdhui"),
    path("echeances/renouveler/<int:pk>/", views.renouveler_contrat_auto, name="renouveler_contrat_auto"),

    # Clients
    path('clients/', views.liste_clients, name='liste_clients'),
    path('clients/<int:pk>/', views.detail_client, name='detail_client'),

    # HTMX endpoints
    path('check-immatriculation/', views.check_immatriculation, name='check_immatriculation'),
    path('check-client/', views.check_client, name='check_client'),
    path('load-sous-categories/', views.load_sous_categories, name='load_sous_categories'),
]
