from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("statistiques/", views.statistiques, name="statistiques"),
]
