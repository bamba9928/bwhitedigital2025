from django import forms

from .models import PaiementApporteur

STANDARD_INPUT_STYLE = (
    "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-900 text-gray-100 "
    "focus:border-green-500 focus:outline-none transition-colors"
)


class ValidationPaiementForm(forms.Form):
    """
    Formulaire côté staff (ADMIN/COMMERCIAL) pour marquer un encaissement comme PAYE
    hors Bictorys (régularisation).
    """

    methode_paiement = forms.CharField(
        max_length=50,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": STANDARD_INPUT_STYLE,
                "placeholder": "Ex: WAVE-SN, OM-SN, CARD, BICTORYS...",
            }
        ),
        help_text="Méthode de paiement utilisée (texte libre).",
    )

    reference_transaction = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": STANDARD_INPUT_STYLE,
                "placeholder": "Référence de la transaction (ID Bictorys / banque, etc.)",
            }
        ),
    )

    def clean_reference_transaction(self):
        ref = (self.cleaned_data.get("reference_transaction") or "").strip()
        if len(ref) < 6:
            raise forms.ValidationError("Référence trop courte (≥ 6 caractères).")
        return ref
