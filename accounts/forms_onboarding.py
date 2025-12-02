import base64
import puremagic as magic
from django import forms
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils import timezone
from django.db import transaction
from PIL import Image
from io import BytesIO

# Assure-toi que le chemin d'import est bon selon ton arborescence
from .models_onboarding import ApporteurOnboarding

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}
MAX_UPLOAD = 5 * 1024 * 1024
MAX_SIGNATURE_SIZE = 2 * 1024 * 1024


class OnboardingForm(forms.ModelForm):
    # Champ explicite pour la checkbox légale
    a_lu_et_approuve = forms.BooleanField(
        label="J'ai lu et j'accepte le contrat et les conditions",
        required=True,
        error_messages={'required': "Vous devez accepter les conditions pour continuer."}
    )

    signature_data_url = forms.CharField(widget=forms.HiddenInput(), required=False)

    # Widget accept pour faciliter la vie sur mobile (ouvre la caméra/galerie filtrée)
    cni_recto = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"accept": "image/*,application/pdf"})
    )
    cni_verso = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"accept": "image/*,application/pdf"})
    )

    class Meta:
        model = ApporteurOnboarding
        fields = ["a_lu_et_approuve", "cni_recto", "cni_verso"]

    def clean_signature_data_url(self):
        """Valide la signature et retourne un ContentFile ou None si inchangée."""
        data_url = self.cleaned_data.get('signature_data_url')

        # Cas 1: Pas de nouvelle signature envoyée
        if not data_url:
            # Si on édite une instance qui a déjà une signature, c'est bon
            if self.instance.pk and self.instance.signature_image:
                return None
            raise ValidationError("La signature est obligatoire.")

        # Cas 2: Validation du format
        if not data_url.startswith("data:image/"):
            raise ValidationError("Format de signature invalide.")

        try:
            header, b64 = data_url.split(",", 1)
            decoded = base64.b64decode(b64)

            if len(decoded) > MAX_SIGNATURE_SIZE:
                raise ValidationError(f"Signature trop volumineuse (max {MAX_SIGNATURE_SIZE // 1024 // 1024}MB).")

            # Vérification image valide via PIL
            with Image.open(BytesIO(decoded)) as img:
                img.verify()  # Lève une exception si l'image est corrompue

            # Détermination extension
            ext = "png" if "png" in header else "jpg"
            filename = f"sig_{self.instance.user.id}_{int(timezone.now().timestamp())}.{ext}"

            return ContentFile(decoded, name=filename)

        except Exception as e:
            # En prod, on logguerait 'e' ici
            raise ValidationError("Signature invalide ou corrompue.")

    def _validate_file(self, f, label):
        """Validation robuste avec détection réelle du type (Magic Numbers)."""
        if not f:
            return f

        # Sauvegarde de la position du curseur
        initial_pos = f.tell()
        try:
            # Lecture du début du fichier pour détection
            first_chunk = f.read(2048)
            f.seek(initial_pos)  # Rembobinage immédiat

            try:
                mime = magic.from_buffer(first_chunk, mime=True)
            except Exception:
                # Fallback si puremagic échoue (rare)
                mime = getattr(f, "content_type", "")

            if mime not in ALLOWED_CONTENT_TYPES:
                raise ValidationError(
                    f"{label}: Format invalide détecté ({mime}). "
                    f"Formats acceptés : JPG, PNG, PDF."
                )

            if f.size > MAX_UPLOAD:
                raise ValidationError(f"{label}: Fichier trop volumineux (Max {MAX_UPLOAD // 1024 // 1024}MB).")

        except Exception as e:
            raise ValidationError(f"Erreur lors de la lecture du fichier {label}.")

        return f

    def clean_cni_recto(self):
        return self._validate_file(self.cleaned_data.get("cni_recto"), "CNI recto")

    def clean_cni_verso(self):
        return self._validate_file(self.cleaned_data.get("cni_verso"), "CNI verso")

    def clean(self):
        cleaned_data = super().clean()

        # Logique pour vérifier la présence (Nouvel upload OU Fichier existant)
        # self.cleaned_data['cni_recto'] est None si pas d'upload ou si erreur de validation

        has_new_recto = cleaned_data.get("cni_recto")
        has_old_recto = self.instance.pk and self.instance.cni_recto and not self.data.get("cni_recto-clear")

        has_new_verso = cleaned_data.get("cni_verso")
        has_old_verso = self.instance.pk and self.instance.cni_verso and not self.data.get("cni_verso-clear")

        # Si ni nouveau ni ancien -> Erreur
        if not (has_new_recto or has_old_recto):
            self.add_error('cni_recto', "La CNI Recto est obligatoire.")

        if not (has_new_verso or has_old_verso):
            self.add_error('cni_verso', "La CNI Verso est obligatoire.")

        return cleaned_data

    def save(self, commit=True):
        """Sauvegarde avec nettoyage sécurisé des anciens fichiers."""

        # 1. Identifier les anciens fichiers avant modification de l'instance
        old_recto = self.instance.cni_recto if self.instance.pk else None
        old_verso = self.instance.cni_verso if self.instance.pk else None

        # 2. Préparer l'instance
        instance = super().save(commit=False)

        # 3. Assigner la signature si elle a changé (return du clean_signature...)
        signature_file = self.cleaned_data.get('signature_data_url')
        if signature_file:
            instance.signature_image = signature_file

        if commit:
            instance.save()

            # 4. Suppression conditionnelle et différée (Sécurité Transactionnelle)
            def delete_old_files():
                # On revérifie si le fichier a bien changé sur le disque
                try:
                    if old_recto and old_recto != instance.cni_recto:
                        old_recto.delete(save=False)
                    if old_verso and old_verso != instance.cni_verso:
                        old_verso.delete(save=False)
                except Exception:
                    # On ne veut pas faire planter la vue si la suppression de fichier échoue
                    pass

            # On exécute la suppression seulement si la transaction DB est validée
            transaction.on_commit(delete_old_files)

        return instance