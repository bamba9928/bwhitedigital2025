from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('', views.liste_paiements, name='liste_paiements'),
    path('mes-commissions/', views.mes_commissions, name='mes_commissions'),
    path('<int:pk>/valider/', views.valider_paiement, name='valider_paiement'),
    path('recapitulatif/', views.recapitulatif_mensuel, name='recapitulatif_mensuel'),
]