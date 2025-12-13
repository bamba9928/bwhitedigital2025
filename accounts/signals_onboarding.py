from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models_onboarding import ApporteurOnboarding

@receiver(post_save, sender=settings.AUTH_USER_MODEL, dispatch_uid="accounts_ensure_onboarding_v1")
def ensure_onboarding(sender, instance, created, **kwargs):
    if not created:
        return

    if instance.role == "APPORTEUR":
        ApporteurOnboarding.objects.get_or_create(user=instance)