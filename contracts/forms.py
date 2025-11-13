from datetime import date, timedelta

from django import forms
from django.core.cache import cache
from django.core.exceptions import ValidationError

from .api_client import askia_client
from .models import Client, Vehicule
from .referentiels import (
    DUREE_CHOICES,
    CATEGORIES,
    SOUS_CATEGORIES_520,
    SOUS_CATEGORIES_550,
    CARBURANTS,
    MARQUES,
)
from .validators import (
    validate_immatriculation,
    SENEGAL_PHONE_VALIDATOR,
    normalize_phone_for_storage,
)

BASE_INPUT_CLASS = (
    "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-900 text-gray-100 "
    "focus:border-green-500 focus:outline-none transition-all duration-300"
)
BASE_SELECT_CLASS = BASE_INPUT_CLASS
LARGE_INPUT_CLASS = (
    "w-full px-4 py-3 border-2 border-gray-600 rounded-lg bg-gray-900 text-gray-100 "
    "focus:border-green-500 focus:outline-none text-lg font-medium transition-all duration-300"
)


# === CLIENT FORM ===
class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ["prenom", "nom", "telephone", "adresse"]
        labels = {
            "prenom": "Prénom",
            "nom": "Nom",
            "telephone": "Téléphone",
            "adresse": "Adresse",
        }
        widgets = {
            "prenom": forms.TextInput(
                attrs={
                    "class": BASE_INPUT_CLASS,
                    "placeholder": "Prénom du client",
                    "autocomplete": "given-name",
                    "required": "required",
                }
            ),
            "nom": forms.TextInput(
                attrs={
                    "class": BASE_INPUT_CLASS,
                    "placeholder": "Nom du client",
                    "autocomplete": "family-name",
                    "required": "required",
                }
            ),
            "telephone": forms.TextInput(
                attrs={
                    "class": BASE_INPUT_CLASS,
                    "placeholder": "77XXXXXXX",
                    "autocomplete": "tel",
                    # pattern aligné sur les préfixes SN
                    "pattern": r"^(70|71|75|76|77|78|30|33|34)\d{7}$",
                    "inputmode": "numeric",
                    "maxlength": "9",
                    "required": "required",
                }
            ),
            "adresse": forms.Textarea(
                attrs={
                    "class": BASE_INPUT_CLASS,
                    "placeholder": "Adresse complète",
                    "rows": 2,
                    "autocomplete": "street-address",
                    "required": "required",
                    "minlength": "2",
                    "maxlength": "255",
                }
            ),
        }

    def clean_telephone(self):
        tel_raw = (self.cleaned_data.get("telephone") or "").strip()
        # 1) normaliser pour stockage: retirer 00221/221 et non-chiffres
        tel = normalize_phone_for_storage(tel_raw)

        # 2) longueur exacte
        if len(tel) != 9:
            raise ValidationError(
                "Le numéro de téléphone doit contenir exactement 9 chiffres."
            )

        # 3) préfixes valides
        try:
            SENEGAL_PHONE_VALIDATOR(tel)
        except ValidationError:
            raise ValidationError(
                "Préfixe invalide. Autorisés: 70, 71, 75, 76, 77, 78, 30, 33, 34."
            )

        # 4) unicité, en excluant l'instance en cours d’édition
        qs = Client.objects.filter(telephone=tel)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Ce numéro de téléphone est déjà utilisé.")

        return tel

    def clean_prenom(self):
        p = (self.cleaned_data.get("prenom") or "").strip().upper()
        if len(p) < 2:
            raise ValidationError("Prénom trop court")
        return p

    def clean_nom(self):
        n = (self.cleaned_data.get("nom") or "").strip().upper()
        if len(n) < 2:
            raise ValidationError("Nom trop court")
        return n

    def clean_adresse(self):
        adr = (self.cleaned_data.get("adresse") or "").strip()
        if len(adr) < 2:
            raise forms.ValidationError("Adresse trop courte (2 caractères minimum)")
        return adr


# ===============VehiculeForm======================================
class VehiculeForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        # 1) Pré-normaliser les données saisies
        data = kwargs.get("data")
        if data:
            d = data.copy()
            if "immatriculation" in d:
                d["immatriculation"] = (
                    d["immatriculation"]
                    .upper()
                    .replace(" ", "")
                    .replace("--", "-")
                    .strip()
                )
            # zfill éventuel dès la saisie
            sc = (d.get("sous_categorie") or "").strip()
            if sc and sc != "000":
                d["sous_categorie"] = sc.zfill(3)
            kwargs["data"] = d

        super().__init__(*args, **kwargs)

        # Valeur par défaut
        self.fields["charge_utile"].initial = 0

        # 2) Déterminer la catégorie courante
        categorie = None
        if self.data:
            categorie = self.data.get("categorie") or None
        if not categorie:
            categorie = (self.initial or {}).get("categorie") or getattr(
                self.instance, "categorie", None
            )

        # 3) Charger les sous-catégories via cache + fallback
        required = False
        choices = [("", "-- Sélectionner --")]
        if categorie in ("520", "550"):
            cache_key = f"sous_categories_ref_${categorie}"
            api_choices = cache.get(cache_key)
            if api_choices is None:
                try:
                    api_choices = askia_client.get_referentiel_sous_categories(
                        categorie
                    )
                    if not api_choices:
                        raise ValueError("vide")
                except Exception:
                    api_choices = (
                        SOUS_CATEGORIES_520
                        if categorie == "520"
                        else SOUS_CATEGORIES_550
                    )
                # normaliser codes sur 3 chiffres
                api_choices = [(str(code).zfill(3), lib) for code, lib in api_choices]
                cache.set(cache_key, api_choices, timeout=3600)
            choices = [("", "-- Sélectionner --")] + api_choices
            required = True

        f = self.fields["sous_categorie"]
        f.required = required
        f.choices = choices
        f.widget.attrs.update({"id": "id_sous_categorie", "name": "sous_categorie"})

    # Champs
    immatriculation = forms.CharField(
        label="Immatriculation",
        validators=[validate_immatriculation],
        widget=forms.TextInput(
            attrs={
                "class": BASE_INPUT_CLASS,
                "placeholder": "AA-123-AA",
                "style": "text-transform: uppercase;",
                "hx-get": "/contracts/check-immatriculation/",
                "hx-trigger": "blur, change",
                "hx-target": "#immat-error",
                "hx-indicator": "#immat-loading",
                "required": True,
                "autocomplete": "off",
            }
        ),
    )

    marque = forms.ChoiceField(
        label="Marque",
        # MARQUES a déjà parfois une option vide; n’en rajoute pas ici pour éviter le doublon
        choices=MARQUES,
        widget=forms.Select(
            attrs={"class": BASE_SELECT_CLASS, "id": "id_marque", "required": True}
        ),
    )

    categorie = forms.ChoiceField(
        label="Catégorie",
        choices=CATEGORIES,  # évite double option vide
        widget=forms.Select(
            attrs={
                "class": BASE_SELECT_CLASS,
                "id": "id_categorie",
                "name": "categorie",
                "required": True,
                "hx-get": "/contracts/load-sous-categories/",
                "hx-target": "#sous-categorie-wrapper",
                "hx-trigger": "change",
                "hx-swap": "innerHTML",
                "hx-indicator": "#sc-loading",
            }
        ),
    )

    sous_categorie = forms.ChoiceField(
        label="Genre / Sous-catégorie",
        required=False,
        choices=[("", "-- Sélectionner --")],
        widget=forms.Select(
            attrs={
                "class": BASE_SELECT_CLASS,
                "id": "id_sous_categorie",
                "name": "sous_categorie",
            }
        ),
    )

    carburant = forms.ChoiceField(
        label="Carburant",
        choices=CARBURANTS,  # évite double option vide
        widget=forms.Select(
            attrs={"class": BASE_SELECT_CLASS, "id": "id_carburant", "required": True}
        ),
    )

    valeur_neuve = forms.DecimalField(
        required=False, widget=forms.HiddenInput(attrs={"id": "id_valeur_neuve"})
    )
    valeur_venale = forms.DecimalField(
        required=False, widget=forms.HiddenInput(attrs={"id": "id_valeur_venale"})
    )

    class Meta:
        model = Vehicule
        fields = [
            "immatriculation",
            "marque",
            "modele",
            "categorie",
            "sous_categorie",
            "charge_utile",
            "puissance_fiscale",
            "nombre_places",
            "carburant",
            "valeur_neuve",
            "valeur_venale",
        ]
        labels = {
            "modele": "Modèle",
            "charge_utile": "Charge utile (kg)",
            "puissance_fiscale": "Puissance fiscale (CV)",
            "nombre_places": "Nombre de places",
        }
        widgets = {
            "modele": forms.TextInput(
                attrs={
                    "class": BASE_INPUT_CLASS,
                    "placeholder": "Modèle du véhicule",
                    "required": True,
                }
            ),
            "charge_utile": forms.HiddenInput(),
            "puissance_fiscale": forms.NumberInput(
                attrs={
                    "class": BASE_INPUT_CLASS,
                    "min": 1,
                    "max": 50,
                    "placeholder": "Puissance (CV)",
                    "required": True,
                }
            ),
            "nombre_places": forms.NumberInput(
                attrs={
                    "class": BASE_INPUT_CLASS,
                    "min": 1,
                    "max": 100,
                    "placeholder": "Nombre de places",
                    "required": True,
                }
            ),
        }

    # === VALIDATIONS ===
    def clean_modele(self):
        m = (self.cleaned_data.get("modele") or "").strip().upper()
        if len(m) < 2:
            raise ValidationError("Modèle trop court")
        return m

    def clean_sous_categorie(self):
        sc = (self.cleaned_data.get("sous_categorie") or "").strip()
        if sc and sc != "000":
            sc = sc.zfill(3)
        return sc

    def clean_puissance_fiscale(self):
        pf = self.cleaned_data.get("puissance_fiscale")
        if not pf or not (1 <= pf <= 50):
            raise ValidationError("Puissance entre 1 et 50 CV")
        return pf

    def clean_nombre_places(self):
        n = self.cleaned_data.get("nombre_places")
        if not n or not (1 <= n <= 100):
            raise ValidationError("Nombre de places entre 1 et 100")
        return n

    def clean_categorie(self):
        cat = self.cleaned_data.get("categorie")
        if not cat:
            raise ValidationError("Catégorie obligatoire")
        return cat

    def clean(self):
        cleaned = super().clean()
        cat = cleaned.get("categorie")
        sc = cleaned.get("sous_categorie")
        cu = cleaned.get("charge_utile") or 0

        if cat == "520":
            if not sc:
                self.add_error("sous_categorie", "Obligatoire pour TPC")
            cleaned["charge_utile"] = max(3500, min(int(cu), 10000))
        elif cat == "550":
            if not sc:
                self.add_error("sous_categorie", "Obligatoire pour Moto")
            cleaned["charge_utile"] = 0
        else:
            cleaned["sous_categorie"] = "000"  # cohérent API
            cleaned["charge_utile"] = 0
        return cleaned


# === SIMULATION FORM ===
class ContratSimulationForm(forms.Form):
    duree = forms.TypedChoiceField(
        choices=DUREE_CHOICES,
        coerce=int,
        label="Durée du contrat",
        widget=forms.Select(
            attrs={"class": BASE_SELECT_CLASS, "id": "id_duree", "required": True}
        ),
    )
    date_effet = forms.DateField(
        initial=date.today,
        label="Date d'effet",
        widget=forms.DateInput(
            attrs={
                "type": "text",
                "class": LARGE_INPUT_CLASS + " cursor-pointer",
                "id": "id_date_effet",
                "placeholder": "JJ/MM/AAAA",
                "readonly": "readonly",
                "required": True,
            }
        ),
    )

    def clean_date_effet(self):
        d = self.cleaned_data["date_effet"]
        today = date.today()
        if d < today:
            raise ValidationError("Date dans le passé interdite")
        if d > today + timedelta(days=60):
            raise ValidationError("Maximum 60 jours à l’avance")
        return d
