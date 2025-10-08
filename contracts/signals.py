import logging
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.db.models import Q
from payments.models import PaiementApporteur, HistoriquePaiement
from .models import Contrat

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Contrat)
def create_paiement_apporteur(sender, instance, created, **kwargs):
    """
    Crée un paiement UNIQUEMENT pour les contrats VALIDES.
    """
    if not created:
        return

    # ✅ Vérification stricte de validité
    if not instance.is_valide:
        logger.warning(
            "Contrat %s INVALIDE - Raison: %s | Paiement NON créé",
            instance.numero_police or instance.pk,
            instance.raison_invalide
        )
        return

    if not instance.apporteur or instance.apporteur.role != "APPORTEUR":
        return

    if instance.commission_apporteur <= 0:
        logger.info(
            "Contrat %s sans commission apporteur | Paiement NON créé",
            instance.numero_police
        )
        return

    try:
        paiement, was_created = PaiementApporteur.objects.get_or_create(
            contrat=instance,
            defaults={
                "montant_commission": instance.commission_apporteur,
                "montant_verse": instance.net_a_reverser,
                "status": "EN_ATTENTE",
            },
        )

        if was_created:
            HistoriquePaiement.objects.create(
                paiement=paiement,
                action="CREATION",
                effectue_par=instance.apporteur,
                details=f"Paiement créé pour contrat valide {instance.numero_police}",
            )
            logger.info(
                "Paiement créé | Contrat: %s | Commission: %s",
                instance.numero_police, instance.commission_apporteur
            )
        else:
            logger.info(
                "Paiement existe déjà pour contrat %s",
                instance.numero_police
            )
    except Exception as e:
        logger.error(
            "Erreur création paiement pour contrat %s: %s",
            instance.numero_police, e, exc_info=True
        )


@receiver(pre_save, sender=Contrat)
def update_contrat_dates_and_status(sender, instance, **kwargs):
    """
    Met à jour automatiquement les dates et le statut du contrat.
    """
    # Calculer date d'échéance si manquante
    if instance.date_effet and instance.duree and not instance.date_echeance:
        instance.calculate_date_echeance()

    # Calculer commission si manquante
    if instance.commission_apporteur == 0 and instance.apporteur:
        instance.calculate_commission()

    # Définir date d'émission lors du passage à EMIS
    if instance.status == "EMIS" and not instance.emis_at:
        instance.emis_at = timezone.now()

    # Vérification expiration automatique
    if instance.date_echeance and instance.date_echeance < timezone.now().date():
        if instance.status in ["EMIS", "ACTIF"]:
            logger.info(
                "Contrat %s automatiquement EXPIRÉ (échéance: %s)",
                instance.numero_police, instance.date_echeance
            )
            instance.status = "EXPIRE"


@receiver(post_save, sender=PaiementApporteur)
def log_paiement_status_change(sender, instance, created, update_fields, **kwargs):
    """
    Log les changements de statut d'un paiement (sauf à la création).
    """
    if created:
        return  # Déjà tracé dans create_paiement_apporteur

    # Vérifier si le statut a vraiment changé
    if update_fields and 'status' not in update_fields:
        return

    try:
        # Récupérer l'ancien statut depuis la base
        old_paiement = PaiementApporteur.objects.get(pk=instance.pk)

        if old_paiement.status != instance.status:
            HistoriquePaiement.objects.create(
                paiement=instance,
                action="STATUS_CHANGE",
                effectue_par=getattr(instance, "validated_by", None),
                details=(
                    f"Statut changé de {old_paiement.get_status_display()} "
                    f"vers {instance.get_status_display()}"
                ),
            )
            logger.info(
                "Paiement %s | Changement statut: %s → %s",
                instance.pk, old_paiement.status, instance.status
            )
    except PaiementApporteur.DoesNotExist:
        pass
    except Exception as e:
        logger.error(
            "Erreur log changement paiement %s: %s",
            instance.pk, e, exc_info=True
        )