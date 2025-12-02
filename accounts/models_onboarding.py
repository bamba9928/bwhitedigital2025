from django.db import models
from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.utils import timezone


class ApporteurOnboarding(models.Model):
    class Status(models.TextChoices):
        # Nouveau statut pour quand l'utilisateur remplit encore son dossier
        BROUILLON = "BROUILLON", "Brouillon / En cours"
        # L'utilisateur a fini et envoyé le dossier
        EN_ATTENTE_VALIDATION = "EN_ATTENTE_VALIDATION", "En attente de validation"
        VALIDE = "VALIDE", "Validé par l'admin"
        REJETE = "REJETE", "Rejeté (à corriger)"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="onboarding"
    )

    # --- Approbation & Audit ---
    a_lu_et_approuve = models.BooleanField(default=False, verbose_name="Conditions acceptées")
    approuve_at = models.DateTimeField(null=True, blank=True, verbose_name="Date d'approbation")

    version_conditions = models.CharField(max_length=20, default="v1.0")
    ip_accept = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP Acceptation")
    ua_accept = models.TextField(blank=True, default="", verbose_name="User Agent")

    # --- Fichiers (Avec sécurité basique via validation) ---
    # On autorise seulement les images et PDF pour éviter les scripts malveillants
    EXTENSIONS_AUTORISEES = ['pdf', 'jpg', 'jpeg', 'png']

    cni_recto = models.FileField(
        upload_to="onboarding/cni/%Y/%m/",
        null=True, blank=True,
        validators=[FileExtensionValidator(allowed_extensions=EXTENSIONS_AUTORISEES)],
        verbose_name="CNI Recto"
    )
    cni_verso = models.FileField(
        upload_to="onboarding/cni/%Y/%m/",
        null=True, blank=True,
        validators=[FileExtensionValidator(allowed_extensions=EXTENSIONS_AUTORISEES)],
        verbose_name="CNI Verso"
    )
    # Signature est une ImageField, Django valide déjà que c'est une image
    signature_image = models.ImageField(
        upload_to="onboarding/signatures/%Y/%m/",
        null=True, blank=True,
        verbose_name="Signature manuscrite"
    )
    contrat_pdf = models.FileField(
        upload_to="onboarding/contrats/%Y/%m/",
        null=True, blank=True,
        verbose_name="Contrat généré (PDF)"
    )

    # --- État du dossier ---
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.BROUILLON,
        verbose_name="Statut du dossier"
    )
    motif_rejet = models.TextField(blank=True, verbose_name="Motif du rejet (si applicable)")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Onboarding Apporteur"
        verbose_name_plural = "Onboardings Apporteurs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Dossier {self.user.username} ({self.get_status_display()})"

    @property
    def est_complet(self):
        """Vérifie techniquement si les pièces sont là."""
        return bool(
            self.a_lu_et_approuve
            and self.cni_recto
            and self.cni_verso
            and self.signature_image
        )

    def soumettre(self):
        """Transition d'état : passe le dossier en validation si complet."""
        if self.est_complet:
            self.status = self.Status.EN_ATTENTE_VALIDATION
            if not self.approuve_at:
                self.approuve_at = timezone.now()
            self.save()
            return True
        return False