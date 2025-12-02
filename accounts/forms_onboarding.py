import base64
import puremagic as magic
from django import forms
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image
from io import BytesIO

from .models_onboarding import ApporteurOnboarding

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}
MAX_UPLOAD = 5 * 1024 * 1024
MAX_SIGNATURE_SIZE = 2 * 1024 * 1024


class OnboardingForm(forms.ModelForm):
    a_lu_et_approuve = forms.BooleanField(
        label="J'ai lu et j'accepte le contrat et les conditions",
        required=True,
    )

    signature_data_url = forms.CharField(widget=forms.HiddenInput(), required=False)

    cni_recto = forms.FileField(required=False,
                                widget=forms.ClearableFileInput(attrs={"accept": ".jpg,.jpeg,.png,.pdf"}))
    cni_verso = forms.FileField(required=False,
                                widget=forms.ClearableFileInput(attrs={"accept": ".jpg,.jpeg,.png,.pdf"}))

    class Meta:
        model = ApporteurOnboarding
        fields = ["a_lu_et_approuve", "cni_recto", "cni_verso"]

    def clean_signature_data_url(self):
        """Valide la signature et retourne un ContentFile"""
        data_url = self.cleaned_data.get('signature_data_url')
        if not data_url:
            if self.instance and self.instance.signature_image:
                return None
            raise ValidationError("La signature est obligatoire.")

        if not data_url.startswith("data:image/"):
            raise ValidationError("Format de signature invalide.")

        try:
            header, b64 = data_url.split(",", 1)
            decoded = base64.b64decode(b64)

            if len(decoded) > MAX_SIGNATURE_SIZE:
                raise ValidationError(f"Signature trop volumineuse (max {MAX_SIGNATURE_SIZE // 1024 // 1024}MB).")

            # Vérification image valide
            img = Image.open(BytesIO(decoded))
            img.verify()

            ext = "png" if "png" in header else "jpg"
            return ContentFile(decoded, name=f"sig_{self.instance.user.id}_{int(timezone.now().timestamp())}.{ext}")
        except Exception as e:
            raise ValidationError(f"Signature invalide: {e}")

    def _validate_file(self, f, label):
        """Validation robuste avec détection réelle du type"""
        if not f:
            return f

        # Détection type réel
        try:
            mime = magic.from_buffer(f.read(1024), mime=True)
        except Exception:
            mime = getattr(f, "content_type", "")
        finally:
            f.seek(0)

        if mime not in ALLOWED_CONTENT_TYPES:
            raise ValidationError(f"{label}: type réel invalide (détecté: {mime}).")

        if f.size > MAX_UPLOAD:
            raise ValidationError(f"{label}: taille > {MAX_UPLOAD // 1024 // 1024}MB.")

        return f

    def clean_cni_recto(self):
        return self._validate_file(self.cleaned_data.get("cni_recto"), "CNI recto")

    def clean_cni_verso(self):
        return self._validate_file(self.cleaned_data.get("cni_verso"), "CNI verso")

    def clean(self):
        cleaned_data = super().clean()

        # Validation CNI (upload ou existant)
        recto = cleaned_data.get("cni_recto") or (self.instance.cni_recto if self.instance.pk else None)
        verso = cleaned_data.get("cni_verso") or (self.instance.cni_verso if self.instance.pk else None)

        # Effacement explicite
        if self.data.get("cni_recto-clear"):
            recto = None
        if self.data.get("cni_verso-clear"):
            verso = None

        if not recto:
            self.add_error('cni_recto', "La CNI Recto est obligatoire.")
        if not verso:
            self.add_error('cni_verso', "La CNI Verso est obligatoire.")

        return cleaned_data

    def save(self, commit=True):
        """Sauvegarde avec nettoyage des anciens fichiers"""
        old_recto = self.instance.cni_recto if self.instance.pk else None
        old_verso = self.instance.cni_verso if self.instance.pk else None

        instance = super().save(commit=False)

        # Attribution de la signature
        signature_file = self.cleaned_data.get('signature_data_url')
        if signature_file:
            instance.signature_image = signature_file

        if commit:
            # Nettoyage fichiers obsolètes
            if old_recto and old_recto != instance.cni_recto:
                old_recto.delete(save=False)
            if old_verso and old_verso != instance.cni_verso:
                old_verso.delete(save=False)
            instance.save()

        return instance