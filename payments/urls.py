from django.urls import path
from . import views

app_name = "payments"

urlpatterns = [
    # Apporteur
    path("mes-paiements/", views.mes_paiements, name="mes_paiements"),
    path("contrat/<int:contrat_id>/declarer/", views.declarer_paiement, name="declarer_paiement"),

    # Admin
    path("admin/", views.liste_encaissements, name="liste_encaissements"),
    path("admin/<int:paiement_id>/", views.detail_encaissement, name="detail_encaissement"),
    path("admin/<int:paiement_id>/valider/", views.valider_encaissement, name="valider_encaissement"),
]
