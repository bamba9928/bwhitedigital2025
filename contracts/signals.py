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
    Crée l’encaissement exactement une fois.
    Gère la différence entre APPORTEUR (paie le net) et COMMERCIAL/ADMIN (paie tout le TTC).
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

    if not apporteur:
        return

    # Récupération des modèles
    PaiementApporteur = apps.get_model("payments", "PaiementApporteur")
    HistoriquePaiement = apps.get_model("payments", "HistoriquePaiement")

    # Récupération des montants de base
    prime_ttc = Decimal(getattr(instance, "prime_ttc", 0) or 0)
    commission = Decimal(getattr(instance, "commission_apporteur", 0) or 0)
    montant_du = Decimal("0.00")

    # --- LOGIQUE MÉTIER ---

    # Cas 1 : Apporteur standard
    if getattr(apporteur, "is_apporteur", False):
        # Il garde sa commission à la source, il ne reverse que la différence
        montant_du = prime_ttc - commission

    # Cas 2 : Commercial ou Admin (Vente directe)
    elif getattr(apporteur, "is_commercial", False) or getattr(apporteur, "is_admin", False):
        # Ils n'ont pas de commission source, ils encaissent le client et doivent TOUT reverser
        montant_du = prime_ttc

    # Cas autre (sécurité)
    else:
        return

    # Arrondi final
    montant_du = montant_du.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if montant_du <= 0:
        logger.info(
            "Contrat %s: montant_du <= 0 (%s), encaissement non créé.",
            instance.numero_police or instance.pk,
            montant_du
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
            "Encaissement créé | Contrat: %s | Rôle: %s | Montant dû: %s",
            instance.numero_police or instance.pk,
            apporteur.role,
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

    # Calcul des commissions
    # Note : On laisse calculate_commission s'exécuter même pour les commerciaux
    # car cette méthode (dans models.py) gère le fait de mettre commission_apporteur à 0
    # si ce n'est pas un apporteur, mais calcule quand même la part BWHITE/ASKIA.
    if getattr(instance, "commission_askia", None) in (None, 0):
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