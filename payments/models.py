from django.db import models
from django.conf import settings
from django.utils import timezone

from contracts.models import Contrat


class PaiementApporteur(models.Model):
    """Modèle de paiement des commissions apporteur"""

    PAYMENT_METHOD_CHOICES = [
        ('WAVE', 'Wave'),
        ('ORANGE_MONEY', 'Orange Money'),
        ('CASH', 'Espèces'),
        ('VIREMENT', 'Virement bancaire'),
    ]

    STATUS_CHOICES = [
        ('EN_ATTENTE', 'En attente'),
        ('PAYE', 'Payé'),
        ('ANNULE', 'Annulé'),
        ('ECHEC', 'Échec'),
    ]

    # Relation OneToOne avec Contrat
    contrat = models.OneToOneField(
        Contrat,
        on_delete=models.PROTECT,
        related_name='paiement_apporteur',
        verbose_name='Contrat'
    )

    # Montants
    montant_commission = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='Montant commission'
    )

    montant_verse = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='Montant versé à l\'admin'
    )

    # Méthode et statut
    methode_paiement = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        blank=True,
        null=True,
        verbose_name='Méthode de paiement'
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='EN_ATTENTE',
        verbose_name='Statut'
    )

    # Informations de transaction
    reference_transaction = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True,
        verbose_name='Référence de transaction'
    )

    numero_compte = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name='Numéro de compte (Wave/OM)'
    )

    # Dates
    date_paiement = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='Date de paiement'
    )

    date_validation = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='Date de validation'
    )

    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='paiements_valides',
        verbose_name='Validé par'
    )

    # Notes
    notes = models.TextField(
        blank=True,
        verbose_name='Notes'
    )

    # Métadonnées
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Date de création'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Dernière modification'
    )

    class Meta:
        verbose_name = 'Paiement Apporteur'
        verbose_name_plural = 'Paiements Apporteurs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['date_paiement']),
        ]

    def __str__(self):
        return f"Paiement {self.contrat.numero_police} - {self.get_status_display()}"

    def marquer_comme_paye(self, methode, reference=None, validated_by=None):
        """Marque le paiement comme payé"""
        self.status = 'PAYE'
        self.methode_paiement = methode
        self.reference_transaction = reference
        self.date_paiement = timezone.now()
        self.validated_by = validated_by
        self.date_validation = timezone.now() if validated_by else None
        self.save()

    def save(self, *args, **kwargs):
        # Récupérer les montants du contrat
        if not self.montant_commission:
            self.montant_commission = self.contrat.commission_apporteur
        if not self.montant_verse:
            self.montant_verse = self.contrat.net_a_reverser

        super().save(*args, **kwargs)


class HistoriquePaiement(models.Model):
    """Historique des actions sur les paiements"""

    ACTION_CHOICES = [
        ('CREATION', 'Création'),
        ('MODIFICATION', 'Modification'),
        ('VALIDATION', 'Validation'),
        ('ANNULATION', 'Annulation'),
        ('ECHEC', 'Échec de paiement'),
    ]

    paiement = models.ForeignKey(
        PaiementApporteur,
        on_delete=models.CASCADE,
        related_name='historique',
        verbose_name='Paiement'
    )

    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        verbose_name='Action'
    )

    effectue_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name='Effectué par'
    )

    details = models.TextField(
        blank=True,
        verbose_name='Détails'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Date'
    )

    class Meta:
        verbose_name = 'Historique de paiement'
        verbose_name_plural = 'Historiques de paiements'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_action_display()} - {self.created_at}"


class RecapitulatifCommissions(models.Model):
    """Récapitulatif mensuel des commissions par apporteur"""

    apporteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='recapitulatifs',
        verbose_name='Apporteur'
    )

    mois = models.DateField(
        verbose_name='Mois'
    )

    # Statistiques
    nombre_contrats = models.IntegerField(
        default=0,
        verbose_name='Nombre de contrats'
    )

    total_primes_ttc = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name='Total primes TTC'
    )

    total_commissions = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name='Total commissions'
    )

    total_verse = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name='Total versé'
    )

    total_en_attente = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name='Total en attente'
    )

    # Métadonnées
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Date de création'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Dernière mise à jour'
    )

    class Meta:
        verbose_name = 'Récapitulatif commissions'
        verbose_name_plural = 'Récapitulatifs commissions'
        unique_together = ['apporteur', 'mois']
        ordering = ['-mois']

    def __str__(self):
        return f"{self.apporteur.get_full_name()} - {self.mois.strftime('%B %Y')}"

    @classmethod
    def update_or_create_for_month(cls, apporteur, date):
        """Met à jour ou crée le récapitulatif pour un mois donné"""
        from django.db.models import Sum, Count
        from datetime import date as dt

        # Premier jour du mois
        mois = dt(date.year, date.month, 1)

        # Calculer les statistiques
        contrats = Contrat.objects.filter(
            apporteur=apporteur,
            created_at__year=date.year,
            created_at__month=date.month,
            status='EMIS'
        )

        stats = contrats.aggregate(
            nombre=Count('id'),
            primes=Sum('prime_ttc'),
            commissions=Sum('commission_apporteur'),
            verse=Sum('net_a_reverser')
        )

        # Calculer les paiements en attente
        paiements_en_attente = PaiementApporteur.objects.filter(
            contrat__apporteur=apporteur,
            status='EN_ATTENTE',
            created_at__year=date.year,
            created_at__month=date.month
        ).aggregate(
            total=Sum('montant_commission')
        )

        # Créer ou mettre à jour
        recap, created = cls.objects.update_or_create(
            apporteur=apporteur,
            mois=mois,
            defaults={
                'nombre_contrats': stats['nombre'] or 0,
                'total_primes_ttc': stats['primes'] or 0,
                'total_commissions': stats['commissions'] or 0,
                'total_verse': stats['verse'] or 0,
                'total_en_attente': paiements_en_attente['total'] or 0,
            }
        )

        return recap