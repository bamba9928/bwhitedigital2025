from django.apps import AppConfig
import importlib


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Gestion des utilisateurs"

    def ready(self):
        for mod in ("accounts.signals_onboarding",):
            try:
                importlib.import_module(mod)
            except ModuleNotFoundError:
                pass
