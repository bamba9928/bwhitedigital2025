from django.db import models
from django.conf import settings


class ApporteurOnboarding(models.Model):

    class Status(models.TextChoices):
        EN_ATTENTE_VALIDATION = "EN_ATTENTE_VALIDATION", "En attente de validation"
        SOUMIS = "SOUMIS", "Soumis par l'apporteur"
        VALIDE = "VALIDE", "Validé par l’admin"
        REJETE = "REJETE", "Rejeté"

    # --- Champs du modèle ---
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="onboarding"
    )

    # Approbation
    a_lu_et_approuve = models.BooleanField(default=False)
    approuve_at = models.DateTimeField(null=True, blank=True)

    # Fichiers
    cni_recto = models.FileField(
        upload_to="onboarding/cni/%Y/%m/", null=True, blank=True
    )
    cni_verso = models.FileField(
        upload_to="onboarding/cni/%Y/%m/", null=True, blank=True
    )
    signature_image = models.ImageField(
        upload_to="onboarding/signatures/%Y/%m/", null=True, blank=True
    )
    contrat_pdf = models.FileField(
        upload_to="onboarding/contrats/%Y/%m/", null=True, blank=True
    )

    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.EN_ATTENTE_VALIDATION
    )

    # Métadonnées et Audit
    version_conditions = models.CharField(max_length=20, default="v1.0")
    ip_accept = models.GenericIPAddressField(null=True, blank=True)
    ua_accept = models.TextField(blank=True, default="")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        # get_status_display() récupère la version lisible du statut
        return (
            "Onboarding de {self.user.username} - Statut: {self.get_status_display()}"
        )

    # --- Méthodes personnalisées ---
    def est_complet(self):
        """Vérifie si tous les documents requis ont été fournis."""
        return (
            self.a_lu_et_approuve
            and self.cni_recto
            and self.cni_verso
            and self.signature_image
        )
