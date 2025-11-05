from django import forms
from django.core.exceptions import ValidationError
from .models import Client, Vehicule
from datetime import date
from .referentiels import DUREE_CHOICES, CATEGORIES, SOUS_CATEGORIES_520, SOUS_CATEGORIES_550, CARBURANTS, MARQUES

BASE_INPUT_CLASS = (
    'w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-900 text-gray-100 '
    'focus:border-green-500 focus:outline-none transition-all duration-300'
)
BASE_SELECT_CLASS = BASE_INPUT_CLASS
LARGE_INPUT_CLASS = (
    'w-full px-4 py-3 border-2 border-gray-600 rounded-lg bg-gray-900 text-gray-100 '
    'focus:border-green-500 focus:outline-none text-lg font-medium transition-all duration-300'
)


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['prenom', 'nom', 'telephone', 'adresse']
        labels = {
            'prenom': 'Prénom',
            'nom': 'Nom',
            'telephone': 'Téléphone',
            'adresse': 'Adresse'
        }
        widgets = {
            'prenom': forms.TextInput(attrs={
                'class': BASE_INPUT_CLASS,
                'placeholder': 'Prénom du client',
                'autocomplete': 'given-name'
            }),
            'nom': forms.TextInput(attrs={
                'class': BASE_INPUT_CLASS,
                'placeholder': 'Nom du client',
                'autocomplete': 'family-name'
            }),
            'telephone': forms.TextInput(attrs={
                'class': BASE_INPUT_CLASS,
                'placeholder': '77XXXXXXX',
                'autocomplete': 'tel',
                'pattern': '[0-9]{9}',
                'inputmode': 'numeric'
            }),
            'adresse': forms.Textarea(attrs={
                'class': BASE_INPUT_CLASS,
                'placeholder': 'Adresse complète',
                'rows': 2,
                'autocomplete': 'street-address'
            }),
        }

    def clean_telephone(self):
        tel = ''.join(filter(str.isdigit, (self.cleaned_data.get('telephone') or '').strip()))
        if len(tel) != 9:
            raise ValidationError("Le numéro doit contenir exactement 9 chiffres")
        if not tel.startswith(('70', '75', '76', '77', '78', '30', '33', '34')):
            raise ValidationError("Préfixe invalide (70,75,76,77,78,30,33,34)")
        return tel

    def clean_prenom(self):
        p = (self.cleaned_data.get('prenom') or '').strip()
        return p.upper() if p else p  # Cohérent avec le reste de l'app

    def clean_nom(self):
        n = (self.cleaned_data.get('nom') or '').strip()
        return n.upper() if n else n


class VehiculeForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Normalisation de l'immatriculation dans les données POST
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

    immatriculation = forms.CharField(
        label="Immatriculation",
        validators=Vehicule.immat_validators,
        widget=forms.TextInput(attrs={
            'class': BASE_INPUT_CLASS,
            'placeholder': 'AA-123-AA',
            'style': 'text-transform: uppercase;',
            'hx-get': '/contracts/check-immatriculation/',
            'hx-trigger': 'blur changed',
            'hx-target': '#immat-error',
            'hx-indicator': '#immat-loading'
        })
    )

    marque = forms.ChoiceField(
        label="Marque",
        choices=[('', '-- Sélectionner --')] + list(MARQUES),
        widget=forms.Select(attrs={
            'class': BASE_SELECT_CLASS,
            'id': 'id_marque'
        })
    )

    marque_label = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'marque_label'})
    )

    categorie = forms.ChoiceField(
        label="Catégorie",
        choices=[('', '-- Sélectionner --')] + list(CATEGORIES),
        widget=forms.Select(attrs={
            'class': BASE_SELECT_CLASS,
            'id': 'id_categorie'
        })
    )

    ALL_SOUS_CATEGORIES = list(dict.fromkeys(SOUS_CATEGORIES_520 + SOUS_CATEGORIES_550))

    sous_categorie = forms.ChoiceField(
        label="Genre / Sous-catégorie",
        required=False,
        choices=ALL_SOUS_CATEGORIES,  # Utilise la liste fusionnée
        widget=forms.Select(attrs={
            'class': BASE_SELECT_CLASS,
            'id': 'id_sous_categorie'
        })
    )
    carburant = forms.ChoiceField(
        label="Carburant",
        choices=[('', '-- Sélectionner --')] + list(CARBURANTS),
        widget=forms.Select(attrs={
            'class': BASE_SELECT_CLASS,
            'id': 'id_carburant'
        })
    )

    valeur_neuve = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput()
    )

    valeur_venale = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput()
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
                'placeholder': 'Modèle du véhicule'
            }),
            'charge_utile': forms.HiddenInput(attrs={
                'id': 'id_charge_utile'  # l'ID pour le Javascript
            }),
            'puissance_fiscale': forms.NumberInput(attrs={
                'class': BASE_INPUT_CLASS,
                'placeholder': 'Puissance (CV)',
                'min': '1',
                'max': '50'
            }),
            'nombre_places': forms.NumberInput(attrs={
                'class': BASE_INPUT_CLASS,
                'placeholder': 'Nombre de places',
                'min': '1',
                'max': '100'
            }),
        }

    def clean_modele(self):
        m = (self.cleaned_data.get('modele') or '').strip()
        return m.upper() if m else m

    def clean_puissance_fiscale(self):
        pf = self.cleaned_data.get('puissance_fiscale')
        if pf and not (1 <= pf <= 50):
            raise ValidationError("La puissance fiscale doit être entre 1 et 50 CV")
        return pf

    def clean_nombre_places(self):
        n = self.cleaned_data.get('nombre_places')
        if n and not (1 <= n <= 100):
            raise ValidationError("Le nombre de places doit être entre 1 et 100")
        return n


class ContratSimulationForm(forms.Form):
    duree = forms.ChoiceField(
        choices=DUREE_CHOICES,
        label="Durée du contrat",
        widget=forms.Select(attrs={
            'class': BASE_SELECT_CLASS,
            'id': 'id_duree'
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
            'autocomplete': 'off'
        })
    )

    def clean_date_effet(self):
        d = self.cleaned_data.get('date_effet')
        if not d:
            raise ValidationError("La date d'effet est obligatoire")
        if d < date.today():
            raise ValidationError("La date d'effet ne peut pas être dans le passé")
        if (d - date.today()).days > 60:
            raise ValidationError("La date d'effet ne peut pas dépasser 60 jours")
        return d