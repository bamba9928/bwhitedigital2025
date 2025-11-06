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
                'autocomplete': 'given-name',
                'required': True
            }),
            'nom': forms.TextInput(attrs={
                'class': BASE_INPUT_CLASS,
                'placeholder': 'Nom du client',
                'autocomplete': 'family-name',
                'required': True
            }),
            'telephone': forms.TextInput(attrs={
                'class': BASE_INPUT_CLASS,
                'placeholder': '77XXXXXXX',
                'autocomplete': 'tel',
                'pattern': '[0-9]{9}',
                'inputmode': 'numeric',
                'maxlength': '9',
                'required': True
            }),
            'adresse': forms.Textarea(attrs={
                'class': BASE_INPUT_CLASS,
                'placeholder': 'Adresse complète',
                'rows': 2,
                'autocomplete': 'street-address',
                'required': True
            }),
        }

    def clean_telephone(self):
        """Valide et normalise le numéro de téléphone"""
        tel_raw = self.cleaned_data.get('telephone', '').strip()
        if not tel_raw:
            raise ValidationError("Le numéro de téléphone est obligatoire")

        # Extraction des chiffres uniquement
        tel = ''.join(filter(str.isdigit, tel_raw))

        if len(tel) != 9:
            raise ValidationError("Le numéro doit contenir exactement 9 chiffres")

        PREFIXES_VALIDES = ('70', '75', '76', '77', '78', '30', '33', '34')
        if not tel.startswith(PREFIXES_VALIDES):
            raise ValidationError(
                f"Préfixe invalide. Préfixes acceptés : {', '.join(PREFIXES_VALIDES)}"
            )

        return tel

    def clean_prenom(self):
        """Normalise le prénom en majuscules"""
        prenom = self.cleaned_data.get('prenom', '').strip()
        if not prenom:
            raise ValidationError("Le prénom est obligatoire")
        if len(prenom) < 2:
            raise ValidationError("Le prénom doit contenir au moins 2 caractères")
        return prenom.upper()

    def clean_nom(self):
        """Normalise le nom en majuscules"""
        nom = self.cleaned_data.get('nom', '').strip()
        if not nom:
            raise ValidationError("Le nom est obligatoire")
        if len(nom) < 2:
            raise ValidationError("Le nom doit contenir au moins 2 caractères")
        return nom.upper()

    def clean_adresse(self):
        """Valide l'adresse"""
        adresse = self.cleaned_data.get('adresse', '').strip()
        if not adresse:
            raise ValidationError("L'adresse est obligatoire")
        if len(adresse) < 10:
            raise ValidationError("L'adresse doit contenir au moins 10 caractères")
        return adresse


class VehiculeForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Normalisation de l'immatriculation dans les données POST
        if self.data:
            data = self.data.copy()
            if 'immatriculation' in data and data['immatriculation']:
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

    marque_label = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'marque_label'})
    )

    categorie = forms.ChoiceField(
        label="Catégorie",
        choices=[('', '-- Sélectionner --')] + list(CATEGORIES),
        widget=forms.Select(attrs={
            'class': BASE_SELECT_CLASS,
            'id': 'id_categorie',
            'required': True
        })
    )

    # Fusion des choix pour permettre la validation des deux types
    ALL_SOUS_CATEGORIES = list(dict.fromkeys(SOUS_CATEGORIES_520 + SOUS_CATEGORIES_550))

    sous_categorie = forms.ChoiceField(
        label="Genre / Sous-catégorie",
        required=False,
        choices=[('', '-- Sélectionner --')] + ALL_SOUS_CATEGORIES,
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
            'sous_categorie': 'Genre / Sous-catégorie',
        }
        widgets = {
            'modele': forms.TextInput(attrs={
                'class': BASE_INPUT_CLASS,
                'placeholder': 'Modèle du véhicule',
                'required': True
            }),
            'charge_utile': forms.HiddenInput(attrs={'id': 'id_charge_utile'}),
            'puissance_fiscale': forms.NumberInput(attrs={
                'class': BASE_INPUT_CLASS,
                'placeholder': 'Puissance (CV)',
                'min': '1',
                'max': '50',
                'required': True
            }),
            'nombre_places': forms.NumberInput(attrs={
                'class': BASE_INPUT_CLASS,
                'placeholder': 'Nombre de places',
                'min': '1',
                'max': '100',
                'required': True
            }),
        }

    def clean_modele(self):
        """Normalise le modèle en majuscules"""
        modele = self.cleaned_data.get('modele', '').strip()
        if not modele:
            raise ValidationError("Le modèle est obligatoire")
        if len(modele) < 2:
            raise ValidationError("Le modèle doit contenir au moins 2 caractères")
        return modele.upper()

    def clean_puissance_fiscale(self):
        """Valide la puissance fiscale"""
        pf = self.cleaned_data.get('puissance_fiscale')
        if pf is None:
            raise ValidationError("La puissance fiscale est obligatoire")
        if not (1 <= pf <= 50):
            raise ValidationError("La puissance fiscale doit être entre 1 et 50 CV")
        return pf

    def clean_nombre_places(self):
        """Valide le nombre de places"""
        n = self.cleaned_data.get('nombre_places')
        if n is None:
            raise ValidationError("Le nombre de places est obligatoire")
        if not (1 <= n <= 100):
            raise ValidationError("Le nombre de places doit être entre 1 et 100")
        return n

    def clean_categorie(self):
        """Valide la catégorie"""
        categorie = self.cleaned_data.get('categorie')
        if not categorie:
            raise ValidationError("La catégorie est obligatoire")
        return categorie

    def clean_marque(self):
        """Valide la marque"""
        marque = self.cleaned_data.get('marque')
        if not marque:
            raise ValidationError("La marque est obligatoire")
        return marque

    def clean_carburant(self):
        """Valide le carburant"""
        carburant = self.cleaned_data.get('carburant')
        if not carburant:
            raise ValidationError("Le carburant est obligatoire")
        return carburant

    def clean(self):
        """Validation globale du formulaire"""
        cleaned_data = super().clean()
        categorie = cleaned_data.get('categorie')
        sous_categorie = cleaned_data.get('sous_categorie')
        charge_utile = cleaned_data.get('charge_utile')

        # Validation conditionnelle de la sous-catégorie
        if categorie in ['520', '550']:  # TPC ou Moto
            if not sous_categorie:
                self.add_error(
                    'sous_categorie',
                    "La sous-catégorie est obligatoire pour cette catégorie"
                )

        # Validation de la charge utile pour les TPC
        if categorie == '520':  # TPC
            if not charge_utile or charge_utile <= 0:
                cleaned_data['charge_utile'] = 3500
            elif charge_utile > 10000:
                self.add_error(
                    'charge_utile',
                    "La charge utile ne peut pas dépasser 10000 kg"
                )
        else:
            # Pour les autres catégories, charge utile = 0
            cleaned_data['charge_utile'] = 0

        return cleaned_data


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
            'autocomplete': 'off',
            'required': True
        })
    )

    def clean_duree(self):
        """Valide la durée du contrat"""
        duree = self.cleaned_data.get('duree')
        if not duree:
            raise ValidationError("La durée du contrat est obligatoire")

        # Vérification que la valeur existe dans les choix
        durees_valides = [str(choice[0]) for choice in DUREE_CHOICES]
        if duree not in durees_valides:
            raise ValidationError("Durée de contrat invalide")

        return duree

    def clean_date_effet(self):
        """Valide la date d'effet du contrat"""
        d = self.cleaned_data.get('date_effet')

        if not d:
            raise ValidationError("La date d'effet est obligatoire")

        today = date.today()

        # Vérification date passée
        if d < today:
            raise ValidationError("La date d'effet ne peut pas être dans le passé")

        # Vérification limite 60 jours
        max_date = today + timedelta(days=60)
        if d > max_date:
            raise ValidationError(
                f"La date d'effet ne peut pas dépasser 60 jours "
                f"(maximum : {max_date.strftime('%d/%m/%Y')})"
            )

        return d