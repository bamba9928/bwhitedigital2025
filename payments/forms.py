from django import forms
from .models import PaiementApporteur

# Limite explicitement aux deux méthodes: Orange Money et Wave
OM_WAVE_CHOICES = (("OM", "Orange Money"), ("WAVE", "Wave"))

class DeclarationPaiementForm(forms.ModelForm):
    methode_paiement = forms.ChoiceField(choices=OM_WAVE_CHOICES, widget=forms.Select(attrs={"class": "form-select"}))

    class Meta:
        model = PaiementApporteur
        fields = ["methode_paiement", "reference_transaction", "numero_compte", "notes"]
        widgets = {
            "reference_transaction": forms.TextInput(attrs={"class": "form-input"}),
            "numero_compte": forms.TextInput(attrs={"class": "form-input"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-textarea"}),
        }

class ValidationPaiementForm(forms.Form):
    methode_paiement = forms.ChoiceField(choices=OM_WAVE_CHOICES)
    reference_transaction = forms.CharField(max_length=64, required=True)
