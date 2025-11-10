from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class PaiementApporteur(models.Model):
    """
    Encaissement du net à reverser par l'apporteur vers l'admin BWHITE.
    Créé automatiquement pour un Contrat valide.
    """

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
        "contracts.Contrat",
        on_delete=models.CASCADE,
        related_name="encaissement",
        verbose_name="Contrat",
    )

    # Sommes
    montant_a_payer = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Montant dû par l'apporteur à BWHITE (Prime TTC - sa commission)",
        verbose_name="Montant à payer",
    )

    # Statut et déclaration
    status = models.CharField(
        max_length=12,
        choices=STATUS,
        default="EN_ATTENTE",
        verbose_name="Statut",
    )
    methode_paiement = models.CharField(
        max_length=8,
        choices=METHODE,
        blank=True,
        verbose_name="Méthode de paiement",
    )
    reference_transaction = models.CharField(
        max_length=64,
        blank=True,
        verbose_name="Référence transaction",
    )
    numero_compte = models.CharField(
        max_length=32,
        blank=True,
        verbose_name="N° compte/Wallet déclarant",
        help_text="N° OM ou Wave fourni par l'apporteur",
    )
    notes = models.TextField(blank=True, verbose_name="Notes internes")

    # Traces
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        verbose_name = "Encaissement apporteur"
        verbose_name_plural = "Encaissements apporteurs"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status"])]
        constraints = [
            models.CheckConstraint(
                check=models.Q(montant_a_payer__gte=Decimal("0.00")),
                name="paiement_montant_non_negatif",
            ),
        ]

    def __str__(self):
        ref = self.contrat.numero_police or f"Contrat#{self.contrat_id}"
        return f"Encaissement {ref} - {self.get_status_display()}"

    @property
    def est_paye(self) -> bool:
        return self.status == "PAYE"

    @property
    def est_en_attente(self) -> bool:
        return self.status == "EN_ATTENTE"

    # --- Transitions d’état ---
    def marquer_comme_paye(self, methode: str, reference: str, validated_by=None):
        """
        Validation côté admin: marque l'encaissement comme PAYE.
        """
        if self.status == "PAYE":
            raise ValueError("Déjà marqué comme PAYE.")
        if self.status == "ANNULE":
            raise ValueError("Encaissement annulé. Impossible de valider.")
        if methode not in dict(self.METHODE):
            raise ValueError("Méthode de paiement invalide.")
        if not reference or len(reference.strip()) < 6:
            raise ValueError("Référence transaction invalide.")

        self.methode_paiement = methode
        self.reference_transaction = reference.strip()
        self.status = "PAYE"
        self.save(update_fields=[
            "methode_paiement",
            "reference_transaction",
            "status",
            "updated_at",
        ])

        HistoriquePaiement.objects.create(
            paiement=self,
            action="VALIDATION",
            effectue_par=validated_by,
            details=(
                f"Paiement validé via {self.get_methode_paiement_display()} "
                f"| Ref={self.reference_transaction}"
            ),
        )

    def annuler(self, reason: str = "", by=None):
        if self.status == "PAYE":
            raise ValueError("Déjà payé. Annulation interdite.")
        if self.status == "ANNULE":
            return
        self.status = "ANNULE"
        self.save(update_fields=["status", "updated_at"])
        HistoriquePaiement.objects.create(
            paiement=self,
            action="STATUS_CHANGE",
            effectue_par=by,
            details=f"Statut -> ANNULE. {reason}".strip(),
        )


class HistoriquePaiement(models.Model):
    """
    Journal des actions sur un encaissement (création, changements de statut, validation, etc.).
    """
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
        verbose_name="Encaissement",
    )
    action = models.CharField(max_length=32, choices=ACTIONS, verbose_name="Action")
    effectue_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Effectué par",
    )
    details = models.TextField(blank=True, verbose_name="Détails")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Horodatage")

    class Meta:
        verbose_name = "Historique encaissement"
        verbose_name_plural = "Historiques encaissements"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_action_display()} • {self.created_at:%Y-%m-%d %H:%M}"
