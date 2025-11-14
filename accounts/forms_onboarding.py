from django import forms
from django.core.exceptions import ValidationError

from .models_onboarding import ApporteurOnboarding

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}
MAX_UPLOAD = 5 * 1024 * 1024  # 5MB


class OnboardingForm(forms.ModelForm):
    a_lu_et_approuve = forms.BooleanField(
        label="J'ai lu et j'accepte le contrat et les conditions",
        required=True,
    )

    # On laisse required=False ici, la logique d'obligation est gérée dans clean()
    cni_recto = forms.FileField(required=False)
    cni_verso = forms.FileField(required=False)

    class Meta:
        model = ApporteurOnboarding
        fields = ["a_lu_et_approuve", "cni_recto", "cni_verso"]
        widgets = {
            "cni_recto": forms.ClearableFileInput(
                attrs={"accept": ".jpg,.jpeg,.png,.pdf"}
            ),
            "cni_verso": forms.ClearableFileInput(
                attrs={"accept": ".jpg,.jpeg,.png,.pdf"}
            ),
        }

    def clean(self):
        cleaned_data = super().clean()

        # Fichiers envoyés avec ce submit
        cni_recto_input = cleaned_data.get("cni_recto")
        cni_verso_input = cleaned_data.get("cni_verso")

        # Fichiers déjà présents en base (avant ce submit)
        recto_existant = self.instance.cni_recto if self.instance.pk else None
        verso_existant = self.instance.cni_verso if self.instance.pk else None

        # Si l'utilisateur coche la case "effacer", on considère qu'il n'y a plus de fichier existant
        if self.data.get("cni_recto-clear"):
            recto_existant = None
        if self.data.get("cni_verso-clear"):
            verso_existant = None

        # Pour valider : soit un fichier uploadé maintenant, soit un fichier déjà stocké
        a_recto = cni_recto_input or recto_existant
        a_verso = cni_verso_input or verso_existant

        if not a_recto:
            self.add_error(
                "cni_recto",
                "La CNI Recto est obligatoire pour valider le dossier.",
            )

        if not a_verso:
            self.add_error(
                "cni_verso",
                "La CNI Verso est obligatoire pour valider le dossier.",
            )

        return cleaned_data

    def _validate_file(self, f, label):
        """
        Validateur réutilisable pour les CNI (PDF ou images).
        """
        if not f:
            return f

        if getattr(f, "content_type", None) not in ALLOWED_CONTENT_TYPES:
            raise ValidationError(f"{label}: type invalide (jpeg/png/pdf).")

        if f.size > MAX_UPLOAD:
            raise ValidationError(f"{label}: taille > 5MB.")

        return f

    def clean_cni_recto(self):
        return self._validate_file(self.cleaned_data.get("cni_recto"), "CNI recto")

    def clean_cni_verso(self):
        return self._validate_file(self.cleaned_data.get("cni_verso"), "CNI verso")
