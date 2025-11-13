from django import forms
from .models import PaiementApporteur


class DeclarationPaiementForm(forms.ModelForm):
    """
    Formulaire côté apporteur.
    Méthode et n° de compte requis. Référence optionnelle.
    (Version alternative "DRY" - Don't Repeat Yourself)
    """

    class Meta:
        model = PaiementApporteur
        fields = ["methode_paiement", "reference_transaction", "numero_compte", "notes"]
        widgets = {
            "methode_paiement": forms.Select(attrs={"class": "form-select"}),
            "reference_transaction": forms.TextInput(attrs={"class": "form-input"}),
            "numero_compte": forms.TextInput(attrs={"class": "form-input"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-textarea"}),
        }

    def __init__(self, *args, **kwargs):
        """
        On surcharge __init__ pour changer la logique "required".
        """
        super().__init__(*args, **kwargs)

        self.fields["methode_paiement"].required = True
        self.fields["numero_compte"].required = True
        # On s'assure que les autres sont bien optionnels
        self.fields["reference_transaction"].required = False
        self.fields["notes"].required = False

    def clean_reference_transaction(self):
        """
        Valide que si une référence est fournie, elle n'est pas trop courte.
        (Cette méthode ne change pas)
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
    methode_paiement = forms.ChoiceField(
        choices=PaiementApporteur.METHODE, required=True
    )
    reference_transaction = forms.CharField(max_length=64, required=True)

    def clean_reference_transaction(self):
        ref = self.cleaned_data["reference_transaction"].strip()
        if len(ref) < 6:
            raise forms.ValidationError("Référence trop courte (≥ 6 caractères).")
        return ref