from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

# Import conditionnel ou local pour éviter les problèmes,
# mais ici l'import du modèle lié (Onboarding) est nécessaire.
from .models_onboarding import ApporteurOnboarding

# On récupère le modèle User de manière dynamique pour accéder aux constantes (Role)
User = get_user_model()

@receiver(post_save, sender=settings.AUTH_USER_MODEL, dispatch_uid="accounts_ensure_onboarding_v1")
def ensure_onboarding(sender, instance, created, **kwargs):
    """
    Crée automatiquement le dossier d'onboarding vide
    dès qu'un utilisateur avec le rôle APPORTEUR est créé.
    """
    # On ne fait rien si c'est une mise à jour
    if not created:
        return

    # Vérification robuste du rôle via l'Enum définie dans le modèle User

    if instance.role == User.Role.APPORTEUR:
        ApporteurOnboarding.objects.get_or_create(user=instance)