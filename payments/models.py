from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction

from contracts.models import Contrat

REFERENCE_MIN_LENGTH = 6


class PaiementApporteur(models.Model):
    """Encaissement du net à reverser par l'apporteur vers BWHITE."""

    STATUS = [
        ("EN_ATTENTE", "En attente"),
        ("PAYE", "Payé"),
        ("ANNULE", "Annulé"),
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
        help_text="Net à reverser (contrat.net_a_reverser).",
        verbose_name="Montant à payer",
    )

    status = models.CharField(
        max_length=12,
        choices=STATUS,
        default="EN_ATTENTE",
    )

    # Libre : valeur renvoyée par Bictorys (WAVE-SN, OM-SN, CARD, etc.)
    methode_paiement = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Méthode utilisée",
        help_text="Renseignée automatiquement par Bictorys ou lors d'une validation manuelle.",
    )
    reference_transaction = models.CharField(
        max_length=64,
        blank=True,
        validators=[RegexValidator(
            regex=r"^[A-Z0-9-]{6,64}$",
            message="Référence alphanumérique de 6-64 caractères",
        )],
    )

    # Nouveau champ
    op_token = models.CharField(
        max_length=128,
        blank=True,
        verbose_name="OpToken Bictorys",
        help_text="Token renvoyé par Bictorys pour les appels GET/PATCH /charges/{id}.",
    )
    reference_transaction = models.CharField(
        max_length=64,
        blank=True,
        validators=[
            RegexValidator(
                regex=r"^[0-9A-Za-z-]{6,64}$",
                message="Référence alphanumérique de 6-64 caractères.",
            )
        ],
        help_text="ID ou référence de transaction renvoyée par Bictorys / la banque.",
    )

    # Optionnel, alimenté par le callback (MSISDN, PAN masqué, etc.)
    numero_compte = models.CharField(
        max_length=32,
        blank=True,
        verbose_name="N° compte/Wallet",
        help_text="Éventuellement rempli par Bictorys (numéro de téléphone, wallet, etc.).",
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
    def _get_montant_attendu(self) -> Decimal | None:
        """
        Montant dû par l'apporteur.

        Référence : net_a_reverser.
        Fallback de sécurité : prime_ttc - commission_askia.
        """
        if not self.contrat_id:
            return None

        contrat = self.contrat

        montant = getattr(contrat, "net_a_reverser", None)
        if montant is None:
            prime_ttc = getattr(contrat, "prime_ttc", None)
            commission_askia = getattr(contrat, "commission_askia", None)
            if prime_ttc is not None and commission_askia is not None:
                montant = prime_ttc - commission_askia

        if montant is None:
            return None

        try:
            return Decimal(montant)
        except Exception:
            return None

    def clean(self):
        """Validation métier robuste (ne doit pas planter)."""
        super().clean()

        montant_attendu = self._get_montant_attendu()
        if montant_attendu is None:
            return

        if self.montant_a_payer is None:
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

    @property
    def montant_paye(self) -> Decimal:
        """Montant effectivement payé (0 si non PAYE)."""
        return self.montant_a_payer if self.est_paye else Decimal("0.00")

    # -----------------------------
    # Transitions
    # -----------------------------
    @transaction.atomic
    def marquer_comme_paye(
        self,
        methode: str,
        reference: str,
        numero_client: str = "",
        validated_by=None,
    ) -> None:
        """
        Transition vers PAYÉ avec historique.

        Typiquement appelée depuis :
        - le webhook Bictorys
        - ou une validation manuelle staff (régularisation).
        """
        if self.est_paye:
            raise ValueError("Déjà payé")
        if self.est_annule:
            raise ValueError("Encaissement annulé")

        reference = (reference or "").strip()
        if len(reference) < REFERENCE_MIN_LENGTH:
            raise ValueError(f"Référence trop courte ({REFERENCE_MIN_LENGTH} min)")

        self.methode_paiement = (methode or "").strip()[:50]
        self.reference_transaction = reference

        if numero_client:
            self.numero_compte = str(numero_client).strip()[:32]

        self.status = "PAYE"

        self.save(
            update_fields=[
                "methode_paiement",
                "reference_transaction",
                "numero_compte",
                "status",
                "updated_at",
            ]
        )

        HistoriquePaiement.objects.create(
            paiement=self,
            action="VALIDATION",
            effectue_par=validated_by,
            details=f"Paiement {self.methode_paiement or 'N/A'} | Ref={reference}",
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
