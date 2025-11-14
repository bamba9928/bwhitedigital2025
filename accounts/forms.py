from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import UserCreationForm, PasswordChangeForm

from contracts.validators import SENEGAL_PHONE_VALIDATOR as phone_validator
from .models import User


# =============================
# 🔹 Mixin de nettoyage commun
# =============================
class CleanUserFieldsMixin:
    def clean_first_name(self):
        val = self.cleaned_data.get("first_name")
        return val.capitalize().strip() if val else val

    def clean_last_name(self):
        val = self.cleaned_data.get("last_name")
        return val.capitalize().strip() if val else val

    def clean_address(self):
        val = self.cleaned_data.get("address")
        return val.strip() if val else val

    def clean_email(self):
        val = self.cleaned_data.get("email")
        if val:
            val = val.lower().strip()
            qs = User.objects.filter(email=val)
            if getattr(self, "instance", None) and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("Cette adresse email est déjà utilisée.")
        return val

    def clean_phone(self):
        val = self.cleaned_data.get("phone")
        if val:
            val = "".join(filter(str.isdigit, val))
            if len(val) != 9:
                raise forms.ValidationError(
                    "Le numéro doit contenir exactement 9 chiffres."
                )
            # la conformité au pattern est faite par phone_validator
            qs = User.objects.filter(phone=val)
            if getattr(self, "instance", None) and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("Ce numéro de téléphone est déjà utilisé.")
        return val
class ApporteurCreationForm(UserCreationForm, CleanUserFieldsMixin):
    phone = forms.CharField(
        label="Téléphone",
        validators=[phone_validator],
        max_length=9,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100 "
                "focus:border-blue-500 focus:outline-none",
                "placeholder": "77XXXXXXX",
                "maxlength": "9",
            }
        ),
    )

    role = forms.ChoiceField(
        label="Rôle",
        choices=[
            ("APPORTEUR", "Apporteur d'affaires"),
            ("COMMERCIAL", "Commercial"),
        ],
        initial="APPORTEUR",
        widget=forms.Select(
            attrs={
                "class": "select2 w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100 "
                         "focus:border-green-500 focus:outline-none",
                "data-placeholder": "Sélectionner un rôle",
            }
        ),
    )

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "phone",
            "address",
            "role",
            "grade",
            "password1",
            "password2",
        ]
        widgets = {
            "username": forms.TextInput(
                attrs={
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100 "
                    "focus:border-blue-500 focus:outline-none",
                    "placeholder": "Nom d'utilisateur",
                }
            ),
            "first_name": forms.TextInput(
                attrs={
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100 "
                    "focus:border-blue-500 focus:outline-none",
                    "placeholder": "Prénom",
                }
            ),
            "last_name": forms.TextInput(
                attrs={
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100 "
                    "focus:border-blue-500 focus:outline-none",
                    "placeholder": "Nom",
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100 "
                    "focus:border-blue-500 focus:outline-none",
                    "placeholder": "Email",
                }
            ),
            "address": forms.Textarea(
                attrs={
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100 "
                    "focus:border-blue-500 focus:outline-none",
                    "placeholder": "Adresse complète",
                    "rows": 3,
                }
            ),
            "grade": forms.Select(
                attrs={
                    "id": "id_grade",
                    "class": "select2 w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100 "
                    "focus:border-green-500 focus:outline-none",
                    "data-placeholder": "Sélectionner un grade",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        # on récupère l'utilisateur qui crée
        self.current_user = kwargs.pop("current_user", None)
        super().__init__(*args, **kwargs)

        # style passwords
        self.fields["password1"].widget.attrs.update(
            {
                "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100 "
                "focus:border-blue-500 focus:outline-none",
                "placeholder": "Mot de passe",
            }
        )
        self.fields["password2"].widget.attrs.update(
            {
                "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100 "
                "focus:border-blue-500 focus:outline-none",
                "placeholder": "Confirmer le mot de passe",
            }
        )

        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["email"].required = True
        self.fields["grade"].required = False  # conditionnel

        # 🔒 Règle métier :
        # - ADMIN : peut créer APPORTEUR / COMMERCIAL
        # - COMMERCIAL : ne peut créer que APPORTEUR
        if self.current_user and getattr(self.current_user, "is_commercial", False):
            self.fields["role"].choices = [
                ("APPORTEUR", "Apporteur d'affaires")
            ]
            self.fields["role"].initial = "APPORTEUR"

    def clean_role(self):
        role = self.cleaned_data.get("role")

        # double sécurité côté serveur
        if (
            self.current_user
            and getattr(self.current_user, "is_commercial", False)
            and role != "APPORTEUR"
        ):
            raise forms.ValidationError(
                "Vous n'êtes pas autorisé à créer un utilisateur avec ce rôle."
            )
        return role

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get("role")
        grade = cleaned_data.get("grade")

        if role == "APPORTEUR":
            if not grade:
                cleaned_data["grade"] = "FREEMIUM"
        elif role == "COMMERCIAL":
            cleaned_data["grade"] = None

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = self.cleaned_data.get("role", "APPORTEUR")

        if user.role == "APPORTEUR":
            user.grade = self.cleaned_data.get("grade", "FREEMIUM")
        else:
            user.grade = None

        user.created_by = getattr(self, "current_user", None)

        if commit:
            user.save()
        return user
# =============================
# 🔹 Mise à jour profil user
# =============================
class ProfileUpdateForm(forms.ModelForm, CleanUserFieldsMixin):
    phone = forms.CharField(
        label="Téléphone",
        validators=[phone_validator],
        max_length=9,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100 "
                "focus:border-blue-500 focus:outline-none",
                "placeholder": "77XXXXXXX",
                "maxlength": "9",
            }
        ),
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "address"]
        widgets = {
            "first_name": forms.TextInput(
                attrs={
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100"
                }
            ),
            "last_name": forms.TextInput(
                attrs={
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100"
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100"
                }
            ),
            "address": forms.Textarea(
                attrs={
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100",
                    "rows": 3,
                }
            ),
        }


# =============================
# 🔹 Mise à jour apporteur admin
# =============================
class AdminApporteurUpdateForm(forms.ModelForm, CleanUserFieldsMixin):
    phone = forms.CharField(
        label="Téléphone",
        validators=[phone_validator],
        max_length=9,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100",
                "placeholder": "77XXXXXXX",
                "maxlength": "9",
            }
        ),
    )

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "address",
            "grade",
            "is_active",
        ]
        widgets = {
            "first_name": forms.TextInput(
                attrs={
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100"
                }
            ),
            "last_name": forms.TextInput(
                attrs={
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100"
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100"
                }
            ),
            "address": forms.Textarea(
                attrs={
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100",
                    "rows": 3,
                }
            ),
            "grade": forms.Select(
                attrs={
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100"
                }
            ),
            "is_active": forms.CheckboxInput(
                attrs={
                    "class": "w-4 h-4 text-blue-600 bg-gray-800 border-gray-600 rounded focus:ring-blue-500"
                }
            ),
        }


# =============================
# 🔹 QuickProfileForm
# =============================
class QuickProfileForm(forms.ModelForm, CleanUserFieldsMixin):
    phone = forms.CharField(
        label="Téléphone",
        validators=[phone_validator],
        max_length=9,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100",
                "placeholder": "77XXXXXXX",
                "maxlength": "9",
            }
        ),
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone"]
        widgets = {
            "first_name": forms.TextInput(
                attrs={
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100"
                }
            ),
            "last_name": forms.TextInput(
                attrs={
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100"
                }
            ),
        }


# =============================
# 🔹 Login form
# =============================
class CustomLoginForm(forms.Form):
    username = forms.CharField(
        label="Nom d'utilisateur ou Email",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100",
                "placeholder": "Nom d'utilisateur ou email",
                "autofocus": True,
            }
        ),
    )
    password = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(
            attrs={
                "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100",
                "placeholder": "Mot de passe",
            }
        ),
    )
    remember_me = forms.BooleanField(
        label="Se souvenir de moi",
        required=False,
        widget=forms.CheckboxInput(
            attrs={"class": "w-4 h-4 text-blue-600 bg-gray-800 border-gray-600 rounded"}
        ),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if username and password:
            # Essayer username
            self.user_cache = authenticate(
                self.request, username=username.lower().strip(), password=password
            )
            # Sinon email
            if self.user_cache is None:
                try:
                    user = User.objects.get(email=username.lower())
                    self.user_cache = authenticate(
                        self.request, username=user.username, password=password
                    )
                except User.DoesNotExist:
                    pass
            if self.user_cache is None:
                raise forms.ValidationError(
                    "Nom d'utilisateur/email ou mot de passe incorrect."
                )
            if not self.user_cache.is_active:
                raise forms.ValidationError("Ce compte est désactivé.")
        return self.cleaned_data

    def get_user(self):
        return self.user_cache


# =============================
# 🔹 Password reset form
# =============================
class PasswordResetForm(forms.Form):
    email = forms.EmailField(
        label="Adresse email",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100",
                "placeholder": "Votre adresse email",
                "autofocus": True,
            }
        ),
    )

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if email:
            email = email.lower().strip()
            if not User.objects.filter(email=email, is_active=True).exists():
                raise forms.ValidationError(
                    "Aucun compte actif trouvé avec cette adresse email."
                )
        return email


# =============================
# 🔹 Password change form
# =============================
class CustomPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update(
                {
                    "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100"
                }
            )
        self.fields["old_password"].label = "Mot de passe actuel"
        self.fields["new_password1"].label = "Nouveau mot de passe"
        self.fields["new_password2"].label = "Confirmer le nouveau mot de passe"


# =============================
# 🔹 Bulk action form
# =============================
class BulkActionForm(forms.Form):
    ACTION_CHOICES = [
        ("", "Choisir une action"),
        ("activate", "Activer"),
        ("deactivate", "Désactiver"),
        ("change_grade_platine", "Passer en grade Platine"),
        ("change_grade_freemium", "Passer en grade Freemium"),
        ("delete", "Supprimer"),
    ]
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        required=True,
        widget=forms.Select(
            attrs={
                "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100"
            }
        ),
    )
    selected_users = forms.CharField(widget=forms.HiddenInput())

    def clean_selected_users(self):
        selected_users = self.cleaned_data.get("selected_users")
        if selected_users:
            try:
                return [int(i.strip()) for i in selected_users.split(",") if i.strip()]
            except ValueError:
                raise forms.ValidationError("IDs utilisateurs invalides.")
        return []


# =============================
# 🔹 Search apporteur form
# =============================
class SearchApporteurForm(forms.Form):
    search = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100",
                "placeholder": "Rechercher par nom, prénom, username ou téléphone...",
            }
        ),
    )
    grade = forms.ChoiceField(
        required=False,
        choices=[("", "Tous les grades")] + User.GRADE_CHOICES,
        widget=forms.Select(
            attrs={
                "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100"
            }
        ),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "Tous les statuts"),
            ("actif", "Actifs"),
            ("inactif", "Inactifs"),
        ],
        widget=forms.Select(
            attrs={
                "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100"
            }
        ),
    )
    date_creation = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "w-full px-4 py-2 border border-gray-600 rounded-lg bg-gray-800 text-gray-100",
            }
        ),
    )
