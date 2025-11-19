from django import forms
from .models import PaiementApporteur

# Style standard du projet (récupéré de contracts/forms.py pour cohérence)
STANDARD_INPUT_STYLE = (
    "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-900 text-gray-100 "
    "focus:border-green-500 focus:outline-none transition-colors"
)

class DeclarationPaiementForm(forms.ModelForm):
    """
    Formulaire côté apporteur.
    """
    class Meta:
        model = PaiementApporteur
        fields = ["methode_paiement", "reference_transaction", "numero_compte", "notes"]
        widgets = {
            "methode_paiement": forms.Select(attrs={
                "class": STANDARD_INPUT_STYLE,
                # Optionnel : ajouter 'id': 'id_methode' si tu veux y brancher Select2 via JS
            }),
            "reference_transaction": forms.TextInput(attrs={
                "class": STANDARD_INPUT_STYLE,
                "placeholder": "Ex: ID transaction OM/Wave"
            }),
            "numero_compte": forms.TextInput(attrs={
                "class": STANDARD_INPUT_STYLE,
                "placeholder": "Ex: 771234567"
            }),
            "notes": forms.Textarea(attrs={
                "rows": 3,
                "class": STANDARD_INPUT_STYLE,
                "placeholder": "Informations complémentaires..."
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["methode_paiement"].required = True
        self.fields["numero_compte"].required = True
        self.fields["reference_transaction"].required = False
        self.fields["notes"].required = False

    def clean_reference_transaction(self):
        ref = self.cleaned_data.get("reference_transaction", "")
        if ref and len(ref.strip()) < 6:
            raise forms.ValidationError("Référence trop courte (≥ 6 caractères).")
        return ref.strip()


class ValidationPaiementForm(forms.Form):
    """
    Formulaire côté admin pour marquer PAYE.
    """
    methode_paiement = forms.ChoiceField(
        choices=PaiementApporteur.METHODE,
        required=True,
        widget=forms.Select(attrs={
            "class": STANDARD_INPUT_STYLE
        })
    )
    reference_transaction = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(attrs={
            "class": STANDARD_INPUT_STYLE,
            "placeholder": "Référence de la transaction de validation"
        })
    )

    def clean_reference_transaction(self):
        ref = self.cleaned_data["reference_transaction"].strip()
        if len(ref) < 6:
            raise forms.ValidationError("Référence trop courte (≥ 6 caractères).")
        return ref