from django.apps import AppConfig
import importlib

class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"
    verbose_name = "Gestion des paiements"

