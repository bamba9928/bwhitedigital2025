import logging
from decimal import Decimal, ROUND_HALF_UP

from django.apps import apps
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Contrat

logger = logging.getLogger(__name__)


# ---------- Contrat : création encaissement apporteur ----------
@receiver(post_save, sender=Contrat, dispatch_uid="contracts_create_or_get_paiement_v2")
def create_or_get_paiement_apporteur(sender, instance: Contrat, created, **kwargs):
    """
    Crée l’encaissement exactement une fois si :
      - le contrat est créé,
      - valide,
      - lié à un apporteur (role='APPORTEUR'),
      - statut éligible (non ANNULE/BROUILLON/DEVIS),
      - montant > 0.
    """
    if not created:
        return

    # Garde-fous statut
    if getattr(instance, "status", None) in {"ANNULE", "BROUILLON", "DEVIS"}:
        logger.info(
            "Contrat %s non éligible (status=%s). Encaissement non créé.",
            instance.numero_police or instance.pk,
            instance.status,
        )
        return

    if not getattr(instance, "is_valide", False):
        logger.warning(
            "Contrat %s INVALIDE - Raison: %s | Paiement NON créé",
            instance.numero_police or instance.pk,
            getattr(instance, "raison_invalide", None),
        )
        return

    apporteur = getattr(instance, "apporteur", None)

    # ✅ Important : n'autoriser que les VRAIS apporteurs (pas les commerciaux)
    if not apporteur or not getattr(apporteur, "is_apporteur", False):
        return

    PaiementApporteur = apps.get_model("payments", "PaiementApporteur")
    HistoriquePaiement = apps.get_model("payments", "HistoriquePaiement")

    prime_ttc = Decimal(getattr(instance, "prime_ttc", 0) or 0)
    commission_apporteur = Decimal(getattr(instance, "commission_apporteur", 0) or 0)

    montant_du = (prime_ttc - commission_apporteur).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if montant_du <= 0:
        logger.info(
            "Contrat %s: montant_du <= 0, encaissement non créé.",
            instance.numero_police or instance.pk,
        )
        return

    # Idempotence stricte + verrouillage transactionnel
    with transaction.atomic():
        paiement, was_created = (
            PaiementApporteur.objects.select_for_update().get_or_create(
                contrat=instance,
                defaults={
                    "montant_a_payer": montant_du,
                    "status": "EN_ATTENTE",
                },
            )
        )

    if was_created:
        HistoriquePaiement.objects.create(
            paiement=paiement,
            action="CREATION",
            effectue_par=apporteur,
            details=f"Encaissement créé pour contrat {instance.numero_police or instance.pk}",
        )
        logger.info(
            "Encaissement créé | Contrat: %s | montant_a_payer: %s",
            instance.numero_police or instance.pk,
            paiement.montant_a_payer,
        )
    else:
        logger.info(
            "Encaissement déjà existant pour contrat %s",
            instance.numero_police or instance.pk,
        )


# ---------- Contrat : calculs avant save ----------
@receiver(pre_save, sender=Contrat, dispatch_uid="contracts_sync_fields_before_save_v2")
def update_contrat_dates_and_status(sender, instance: Contrat, **kwargs):
    """Calcule échéance, commission, timestamps, et expiration."""
    # Échéance
    if instance.date_effet and instance.duree and not instance.date_echeance:
        instance.calculate_date_echeance()

    # ✅ Commission apporteur : uniquement si l'apporteur est un vrai apporteur
    if (
        getattr(instance, "commission_apporteur", None) in (None, 0)
        and getattr(instance, "apporteur", None)
        and getattr(instance.apporteur, "is_apporteur", False)
    ):
        instance.calculate_commission()

    # Datation émission
    if instance.status == "EMIS" and not instance.emis_at:
        instance.emis_at = timezone.now()

    # Expiration automatique
    if instance.date_echeance and instance.date_echeance < timezone.localdate():
        if instance.status in {"EMIS", "ACTIF"}:
            logger.info(
                "Contrat %s automatiquement EXPIRÉ (échéance: %s)",
                instance.numero_police or instance.pk,
                instance.date_echeance,
            )
            instance.status = "EXPIRE"


# ---------- Paiement Apporteur : historique des statuts ----------
PaiementApporteur = apps.get_model("payments", "PaiementApporteur")


@receiver(
    pre_save, sender=PaiementApporteur, dispatch_uid="payments_capture_old_status_v2"
)
def _capture_old_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._old_status = None
        return
    try:
        old = sender.objects.only("status").get(pk=instance.pk)
        instance._old_status = old.status
    except sender.DoesNotExist:
        instance._old_status = None


@receiver(
    post_save, sender=PaiementApporteur, dispatch_uid="payments_log_status_change_v2"
)
def log_paiement_status_change(sender, instance, created, **kwargs):
    if created:
        return

    old_status = getattr(instance, "_old_status", None)
    if old_status and old_status != instance.status:
        HistoriquePaiement = apps.get_model("payments", "HistoriquePaiement")
        choices_map = dict(instance._meta.get_field("status").choices)
        old_label = choices_map.get(old_status, old_status)
        new_label = instance.get_status_display()

        HistoriquePaiement.objects.create(
            paiement=instance,
            action="STATUS_CHANGE",
            effectue_par=getattr(instance, "validated_by", None),
            details=f"Statut changé de {old_label} vers {new_label}",
        )

        logger.info(
            "Paiement %s | Changement statut: %s → %s",
            instance.pk,
            old_status,
            instance.status,
        )
