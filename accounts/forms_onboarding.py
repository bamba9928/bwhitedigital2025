from django import forms
from django.core.exceptions import ValidationError
from .models_onboarding import ApporteurOnboarding

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}
MAX_UPLOAD = 5 * 1024 * 1024  # 5MB


class OnboardingForm(forms.ModelForm):
    a_lu_et_approuve = forms.BooleanField(
        label="J’ai lu et j’accepte le contrat et les conditions",
        required=True
    )

    cni_recto = forms.FileField(required=False)
    cni_verso = forms.FileField(required=False)

    class Meta:
        model = ApporteurOnboarding

        fields = ["a_lu_et_approuve", "cni_recto", "cni_verso"]

        widgets = {
            "cni_recto": forms.ClearableFileInput(attrs={"accept": ".jpg,.jpeg,.png,.pdf"}),
            "cni_verso": forms.ClearableFileInput(attrs={"accept": ".jpg,.jpeg,.png,.pdf"}),
        }

    def _validate_file(self, f, label):
        """
        Notre validateur réutilisable pour les CNI
        (qui peuvent être des PDF ou des images).
        """
        if not f:
            return f

        if getattr(f, "content_type", None) not in ALLOWED_CONTENT_TYPES:
            raise ValidationError(f"{label}: type invalide (jpeg/png/pdf).")

        if f.size > MAX_UPLOAD:
            raise ValidationError(f"{label}: taille > 5MB.")

        return f

    def clean_cni_recto(self):
        return self._validate_file(
            self.cleaned_data.get("cni_recto"),
            "CNI recto"
        )

    def clean_cni_verso(self):
        return self._validate_file(
            self.cleaned_data.get("cni_verso"),
            "CNI verso"
        )
