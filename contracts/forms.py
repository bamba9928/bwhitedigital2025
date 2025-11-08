from django import forms
from django.core.exceptions import ValidationError
from .models import Client, Vehicule
from datetime import date, timedelta
from .referentiels import (
    DUREE_CHOICES,
    CATEGORIES,
    SOUS_CATEGORIES_520,
    SOUS_CATEGORIES_550,
    CARBURANTS,
    MARQUES
)

# === CLASSES CSS COMMUNES ===
BASE_INPUT_CLASS = (
    'w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-900 text-gray-100 '
    'focus:border-green-500 focus:outline-none transition-all duration-300'
)
BASE_SELECT_CLASS = BASE_INPUT_CLASS
LARGE_INPUT_CLASS = (
    'w-full px-4 py-3 border-2 border-gray-600 rounded-lg bg-gray-900 text-gray-100 '
    'focus:border-green-500 focus:outline-none text-lg font-medium transition-all duration-300'
)


# === CLIENT FORM ===
class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['prenom', 'nom', 'telephone', 'adresse']
        labels = {
            'prenom': 'Prénom', 'nom': 'Nom',
            'telephone': 'Téléphone', 'adresse': 'Adresse'
        }
        widgets = {
            'prenom': forms.TextInput(attrs={
                'class': BASE_INPUT_CLASS, 'placeholder': 'Prénom du client',
                'autocomplete': 'given-name', 'required': True
            }),
            'nom': forms.TextInput(attrs={
                'class': BASE_INPUT_CLASS, 'placeholder': 'Nom du client',
                'autocomplete': 'family-name', 'required': True
            }),
            'telephone': forms.TextInput(attrs={
                'class': BASE_INPUT_CLASS, 'placeholder': '77XXXXXXX',
                'autocomplete': 'tel', 'pattern': '[0-9]{9}', 'inputmode': 'numeric',
                'maxlength': '9', 'required': True
            }),
            'adresse': forms.Textarea(attrs={
                'class': BASE_INPUT_CLASS, 'placeholder': 'Adresse complète',
                'rows': 2, 'autocomplete': 'street-address', 'required': True
            }),
        }

    # Validations propres
    def clean_telephone(self):
        tel_raw = self.cleaned_data.get('telephone', '').strip()
        if not tel_raw:
            raise ValidationError("Le numéro de téléphone est obligatoire")
        tel = ''.join(filter(str.isdigit, tel_raw))
        if len(tel) != 9:
            raise ValidationError("Le numéro doit contenir exactement 9 chiffres")
        PREFIXES_VALIDES = ('70', '75', '76', '77', '78', '30', '33', '34')
        if not tel.startswith(PREFIXES_VALIDES):
            raise ValidationError(f"Préfixes valides : {', '.join(PREFIXES_VALIDES)}")
        return tel

    def clean_prenom(self):
        p = self.cleaned_data.get('prenom', '').strip().upper()
        if len(p) < 2:
            raise ValidationError("Prénom trop court")
        return p

    def clean_nom(self):
        n = self.cleaned_data.get('nom', '').strip().upper()
        if len(n) < 2:
            raise ValidationError("Nom trop court")
        return n

    def clean_adresse(self):
        a = self.cleaned_data.get('adresse', '').strip()
        if len(a) < 10:
            raise ValidationError("Adresse trop courte (10 caractères minimum)")
        return a


# === VÉHICULE FORM ===
class VehiculeForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Valeurs par défaut
        self.fields['charge_utile'].initial = 0

        # Normalisation immatriculation
        if self.data:
            data = self.data.copy()
            if 'immatriculation' in data:
                data['immatriculation'] = (
                    data['immatriculation']
                    .upper()
                    .replace(' ', '')
                    .replace('--', '-')
                    .strip()
                )
            self.data = data

    # === CHAMPS DÉCLARÉS MANUELLEMENT ===
    immatriculation = forms.CharField(
        label="Immatriculation",
        validators=Vehicule.immat_validators,
        widget=forms.TextInput(attrs={
            'class': BASE_INPUT_CLASS,
            'placeholder': 'AA-123-AA',
            'style': 'text-transform: uppercase;',
            'hx-get': '/contracts/check-immatriculation/',
            'hx-trigger': 'blur, change',
            'hx-target': '#immat-error',
            'hx-indicator': '#immat-loading',
            'required': True,
            'autocomplete': 'off'
        })
    )

    marque = forms.ChoiceField(
        label="Marque",
        choices=[('', '-- Sélectionner --')] + list(MARQUES),
        widget=forms.Select(attrs={
            'class': BASE_SELECT_CLASS,
            'id': 'id_marque',
            'required': True
        })
    )

    categorie = forms.ChoiceField(
        label="Catégorie",
        choices=[('', '-- Sélectionner --')] + list(CATEGORIES),
        widget=forms.Select(attrs={
            'class': BASE_SELECT_CLASS,
            'id': 'id_categorie',
            'required': True,
            'hx-get': '/contracts/load-sous-categories/',
            'hx-target': '#sous-categorie-wrapper',
            'hx-trigger': 'change, load',  # load = déclenche en édition
            'hx-swap': 'outerHTML',
            'hx-indicator': '#sc-loading',
        })
    )

    # Sous-catégorie : caché + désactivé par défaut
    sous_categorie = forms.ChoiceField(
        label="Genre / Sous-catégorie",
        required=False,
        choices=[('', '-- Sélectionner --')],
        widget=forms.Select(attrs={
            'class': BASE_SELECT_CLASS,
            'id': 'id_sous_categorie',
            'disabled': True,
            'style': 'display: none;'  # caché au départ
        })
    )

    carburant = forms.ChoiceField(
        label="Carburant",
        choices=[('', '-- Sélectionner --')] + list(CARBURANTS),
        widget=forms.Select(attrs={
            'class': BASE_SELECT_CLASS,
            'id': 'id_carburant',
            'required': True
        })
    )

    valeur_neuve = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'id_valeur_neuve'})
    )
    valeur_venale = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'id_valeur_venale'})
    )

    class Meta:
        model = Vehicule
        fields = [
            'immatriculation', 'marque', 'modele', 'categorie', 'sous_categorie',
            'charge_utile', 'puissance_fiscale', 'nombre_places', 'carburant',
            'valeur_neuve', 'valeur_venale'
        ]
        labels = {
            'modele': 'Modèle',
            'charge_utile': 'Charge utile (kg)',
            'puissance_fiscale': 'Puissance fiscale (CV)',
            'nombre_places': 'Nombre de places',
        }
        widgets = {
            'modele': forms.TextInput(attrs={
                'class': BASE_INPUT_CLASS,
                'placeholder': 'Modèle du véhicule',
                'required': True
            }),
            'charge_utile': forms.HiddenInput(),
            'puissance_fiscale': forms.NumberInput(attrs={
                'class': BASE_INPUT_CLASS, 'min': 1, 'max': 50,
                'placeholder': 'Puissance (CV)', 'required': True
            }),
            'nombre_places': forms.NumberInput(attrs={
                'class': BASE_INPUT_CLASS, 'min': 1, 'max': 100,
                'placeholder': 'Nombre de places', 'required': True
            }),
        }

    # === VALIDATIONS ===
    def clean_modele(self):
        m = self.cleaned_data.get('modele', '').strip().upper()
        if len(m) < 2:
            raise ValidationError("Modèle trop court")
        return m

    def clean_puissance_fiscale(self):
        pf = self.cleaned_data.get('puissance_fiscale')
        if not pf or not (1 <= pf <= 50):
            raise ValidationError("Puissance entre 1 et 50 CV")
        return pf

    def clean_nombre_places(self):
        n = self.cleaned_data.get('nombre_places')
        if not n or not (1 <= n <= 100):
            raise ValidationError("Nombre de places entre 1 et 100")
        return n

    def clean_categorie(self):
        cat = self.cleaned_data.get('categorie')
        if not cat:
            raise ValidationError("Catégorie obligatoire")
        return cat

    def clean_sous_categorie(self):
        sc = self.cleaned_data.get('sous_categorie') or ''
        cat = self.cleaned_data.get('categorie')

        if cat in ('520', '550') and not sc:
            raise ValidationError("Sous-catégorie obligatoire pour TPC et Moto")

        valid_520 = dict(SOUS_CATEGORIES_520)
        valid_550 = dict(SOUS_CATEGORIES_550)

        if cat == '520' and sc not in valid_520:
            raise ValidationError("Sous-catégorie invalide pour TPC")
        if cat == '550' and sc not in valid_550:
            raise ValidationError("Sous-catégorie invalide pour Moto")

        return sc

    def clean(self):
        cleaned_data = super().clean()
        cat = cleaned_data.get('categorie')
        sc = cleaned_data.get('sous_categorie')
        cu = cleaned_data.get('charge_utile', 0)

        if cat == '520':  # TPC
            if not sc:
                self.add_error('sous_categorie', "Obligatoire pour TPC")
            cleaned_data['charge_utile'] = max(3500, min(cu, 10000))
        elif cat == '550':  # Moto
            if not sc:
                self.add_error('sous_categorie', "Obligatoire pour Moto")
            cleaned_data['charge_utile'] = 0
        else:
            cleaned_data['charge_utile'] = 0

        return cleaned_data


# === SIMULATION FORM ===
class ContratSimulationForm(forms.Form):
    duree = forms.ChoiceField(
        choices=DUREE_CHOICES,
        label="Durée du contrat",
        widget=forms.Select(attrs={
            'class': BASE_SELECT_CLASS,
            'id': 'id_duree',
            'required': True
        })
    )

    date_effet = forms.DateField(
        initial=date.today,
        label="Date d'effet",
        widget=forms.DateInput(attrs={
            'type': 'text',
            'class': LARGE_INPUT_CLASS + ' cursor-pointer',
            'id': 'id_date_effet',
            'placeholder': 'JJ/MM/AAAA',
            'readonly': 'readonly',
            'required': True
        })
    )

    def clean_date_effet(self):
        d = self.cleaned_data['date_effet']
        today = date.today()
        if d < today:
            raise ValidationError("Date dans le passé interdite")
        if d > today + timedelta(days=60):
            raise ValidationError("Maximum 60 jours à l’avance")
        return d