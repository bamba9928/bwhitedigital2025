from django.apps import AppConfig
import importlib

class ContractsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "contracts"
    verbose_name = "Gestion des contrats"

    def ready(self):
        try:
            importlib.import_module("contracts.signals")
        except ModuleNotFoundError:
            pass
