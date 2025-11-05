from django.db import models
from django.conf import settings

class ApporteurOnboarding(models.Model):
    STATUS = [
        ("EN_ATTENTE_VALIDATION", "En attente de validation"),
        ("SOUMIS", "Soumis par l'apporteur"),
        ("VALIDE", "Validé par l’admin"),
        ("REJETE", "Rejeté"),
    ]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="onboarding")
    a_lu_et_approuve = models.BooleanField(default=False)
    approuve_at = models.DateTimeField(null=True, blank=True)
    cni_recto = models.FileField(upload_to="onboarding/cni/%Y/%m/", null=True, blank=True)
    cni_verso = models.FileField(upload_to="onboarding/cni/%Y/%m/", null=True, blank=True)
    signature_image = models.ImageField(upload_to="onboarding/signatures/%Y/%m/", null=True, blank=True)
    contrat_pdf = models.FileField(upload_to="onboarding/contrats/%Y/%m/", null=True, blank=True)
    status = models.CharField(max_length=24, choices=STATUS, default="EN_ATTENTE_VALIDATION")
    version_conditions = models.CharField(max_length=20, default="v1.0")
    ip_accept = models.GenericIPAddressField(null=True, blank=True)
    ua_accept = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def est_complet(self):
        return self.a_lu_et_approuve and self.cni_recto and self.cni_verso and self.signature_image
