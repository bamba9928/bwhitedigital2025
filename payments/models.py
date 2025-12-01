import re
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction
from contracts.models import Contrat

# Constantes
MAX_UPLOAD = 5 * 1024 * 1024
REFERENCE_MIN_LENGTH = 6
ALLOWED_PHONE_REGEX = re.compile(r"^\d{9}$")


class PaiementApporteur(models.Model):
    """Encaissement du net à reverser par l'apporteur vers BWHITE."""

    STATUS = [
        ("EN_ATTENTE", "En attente"),
        ("PAYE", "Payé"),
        ("ANNULE", "Annulé"),
    ]

    METHODE = [
        ("OM", "Orange Money"),
        ("WAVE", "Wave"),
    ]

    contrat = models.OneToOneField(
        Contrat,
        on_delete=models.CASCADE,
        related_name="encaissement",
        verbose_name="Contrat",
    )

    montant_a_payer = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Prime TTC - commission apporteur",
        verbose_name="Montant à payer",
    )

    status = models.CharField(max_length=12, choices=STATUS, default="EN_ATTENTE")
    methode_paiement = models.CharField(max_length=8, choices=METHODE, blank=True)

    reference_transaction = models.CharField(
        max_length=64,
        blank=True,
        validators=[
            RegexValidator(
                regex=r"^[A-Z0-9-]{6,64}$",
                message="Référence alphanumérique de 6-64 caractères",
            )
        ],
    )

    numero_compte = models.CharField(
        max_length=32,
        blank=True,
        validators=[
            RegexValidator(
                regex=ALLOWED_PHONE_REGEX,
                message="Numéro de 9 chiffres requis",
            )
        ],
        verbose_name="N° compte/Wallet",
    )

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Encaissement apporteur"
        verbose_name_plural = "Encaissements apporteurs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["contrat", "status"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(montant_a_payer__gte=Decimal("0.00")),
                name="paiement_montant_non_negatif",
            ),
            models.CheckConstraint(
                check=models.Q(status__in=["EN_ATTENTE", "PAYE", "ANNULE"]),
                name="status_paiement_valid",
            ),
        ]

    def __str__(self):
        return f"Encaissement Contrat#{self.contrat_id} - {self.get_status_display()}"

    # -----------------------------
    # Helpers métier
    # -----------------------------
    def _get_montant_attendu(self):
        """
        Montant dû par l'apporteur.
        On s'appuie d'abord sur net_a_reverser (déjà calculé côté Contrat),
        sinon fallback sur une éventuelle méthode old.
        """
        if not self.contrat_id:
            return None

        montant = getattr(self.contrat, "net_a_reverser", None)

        if montant is None:
            calc = getattr(self.contrat, "calculer_montant_du_apporteur", None)
            if callable(calc):
                montant = calc()

        if montant is None:
            return None

        try:
            return Decimal(montant)
        except Exception:
            return None

    def clean(self):
        """Validation métier robuste (ne doit jamais planter)."""
        super().clean()

        montant_attendu = self._get_montant_attendu()
        if montant_attendu is None:
            return

        # Tolérance d'arrondi
        if (self.montant_a_payer - montant_attendu).copy_abs() > Decimal("0.01"):

            raise ValidationError(
                f"Incohérent. Montant attendu : {montant_attendu} (contrat {self.contrat_id})"
            )

    def save(self, *args, **kwargs):
        """
        Synchronise automatiquement le montant à payer
        si on crée l'objet ou si le montant est encore à 0.
        Évite les incohérences silencieuses.
        """
        if self.contrat_id and (
            self._state.adding
            or self.montant_a_payer is None
            or self.montant_a_payer == Decimal("0.00")
        ):
            attendu = self._get_montant_attendu()
            if attendu is not None:
                self.montant_a_payer = attendu

        super().save(*args, **kwargs)

    # -----------------------------
    # Props statut
    # -----------------------------
    @property
    def est_paye(self) -> bool:
        return self.status == "PAYE"

    @property
    def est_en_attente(self) -> bool:
        return self.status == "EN_ATTENTE"

    @property
    def est_annule(self) -> bool:
        return self.status == "ANNULE"

    # -----------------------------
    # Transitions
    # -----------------------------
    @transaction.atomic
    def marquer_comme_paye(self, methode: str, reference: str, validated_by=None) -> None:
        """Transition vers PAYÉ avec historique."""
        if self.est_paye:
            raise ValueError("Déjà payé")
        if self.est_annule:
            raise ValueError("Encaissement annulé")
        if methode not in dict(self.METHODE):
            raise ValueError("Méthode invalide")

        reference = reference.strip()
        if len(reference) < REFERENCE_MIN_LENGTH:
            raise ValueError(f"Référence trop courte ({REFERENCE_MIN_LENGTH} min)")

        self.methode_paiement = methode
        self.reference_transaction = reference
        self.status = "PAYE"
        self.save(
            update_fields=[
                "methode_paiement",
                "reference_transaction",
                "status",
                "updated_at",
            ]
        )

        HistoriquePaiement.objects.create(
            paiement=self,
            action="VALIDATION",
            effectue_par=validated_by,
            details=f"Paiement {self.get_methode_paiement_display()} | Ref={reference}",
        )

    @transaction.atomic
    def annuler(self, reason: str = "", by=None) -> None:
        """Transition vers ANNULÉ."""
        if self.est_paye:
            raise ValueError("Impossible d'annuler un paiement payé")
        if self.est_annule:
            return  # Idempotent

        self.status = "ANNULE"
        self.save(update_fields=["status", "updated_at"])

        HistoriquePaiement.objects.create(
            paiement=self,
            action="STATUS_CHANGE",
            effectue_par=by,
            details=f"Annulé. {reason}".strip(),
        )
class HistoriquePaiement(models.Model):
    """Audit trail des modifications sur paiements."""

    ACTIONS = [
        ("CREATION", "Création"),
        ("STATUS_CHANGE", "Changement de statut"),
        ("VALIDATION", "Validation paiement"),
        ("MODIFICATION", "Modification"),
    ]

    paiement = models.ForeignKey(
        PaiementApporteur,
        on_delete=models.CASCADE,
        related_name="historiques",
    )
    action = models.CharField(max_length=32, choices=ACTIONS)
    effectue_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Historique encaissement"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["paiement", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.get_action_display()} • {self.created_at:%Y-%m-%d %H:%M:%S}"
