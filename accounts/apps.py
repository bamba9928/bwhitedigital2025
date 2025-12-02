from django.apps import AppConfig

class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Gestion des utilisateurs"

    def ready(self):
        # On importe simplement le module.
        # si ça échoue, on veut le savoir tout de suite !
        import accounts.signals_onboarding