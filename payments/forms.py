from django import forms
from .models import PaiementApporteur


class DeclarationPaiementForm(forms.ModelForm):
    """
    Formulaire côté apporteur.
    Méthode et n° de compte requis. Référence optionnelle.
    """
    methode_paiement = forms.ChoiceField(
        choices=PaiementApporteur.METHODE,
        widget=forms.Select(attrs={"class": "form-select"}),
        # required=True est la valeur par défaut
    )
    reference_transaction = forms.CharField(
        max_length=64, required=False,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )
    numero_compte = forms.CharField(
        max_length=32, required=True,
        widget=forms.TextInput(attrs={"class": "form-input"})
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-textarea"})
    )

    class Meta:
        model = PaiementApporteur
        fields = ["methode_paiement", "reference_transaction", "numero_compte", "notes"]
    def clean_reference_transaction(self):
        """
        Valide que si une référence est fournie, elle n'est pas trop courte.
        """
        ref = self.cleaned_data.get("reference_transaction", "")
        if ref and len(ref.strip()) < 6:
            raise forms.ValidationError("Référence trop courte (≥ 6 caractères).")
        return ref.strip()


class ValidationPaiementForm(forms.Form):
    """
    Formulaire côté admin pour marquer PAYE.
    Méthode et référence requis.
    (Ce formulaire est parfait)
    """
    methode_paiement = forms.ChoiceField(choices=PaiementApporteur.METHODE, required=True)
    reference_transaction = forms.CharField(max_length=64, required=True)

    def clean_reference_transaction(self):
        ref = self.cleaned_data["reference_transaction"].strip()
        if len(ref) < 6:
            raise forms.ValidationError("Référence trop courte (≥ 6 caractères).")
        return ref