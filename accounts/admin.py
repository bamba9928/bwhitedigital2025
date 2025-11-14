from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin personnalisé pour le modèle User"""

    list_display = (
        "username",
        "get_full_name",
        "email",
        "role",
        "grade",
        "phone",
        "is_active",
        "is_staff",
        "is_superuser",
    )
    list_filter = (
        "role",
        "grade",
        "is_active",
        "is_staff",
        "is_superuser",
        "created_at",
    )
    search_fields = ("username", "first_name", "last_name", "email", "phone")
    ordering = ("-created_at",)

    readonly_fields = ("created_by", "created_at", "updated_at")

    fieldsets = (
        (_("Informations générales"), {
            "fields": (
                "username", "password", "first_name", "last_name",
                "email", "phone", "address", "role"
            )
        }),
        (_("Grade (apporteur uniquement)"), {
            "fields": ("grade",),
            "classes": ("collapse",),
        }),
        (_("Permissions"), {
            "fields": (
                "is_active", "is_staff", "is_superuser",
                "groups", "user_permissions"
            )
        }),
        (_("Suivi"), {
            "fields": ("created_by", "created_at", "updated_at"),
        }),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "username", "password1", "password2",
                "first_name", "last_name", "email", "phone", "address",
                "role", "grade", "is_active", "is_staff", "is_superuser"
            ),
        }),
    )

    class Media:
        js = ("admin/js/user_admin.js",)

    actions = [
        "set_admin",
        "set_commercial",
        "set_apporteur_freemium",
        "set_apporteur_platine",
        "reset_grade",
    ]

    def set_admin(self, request, queryset):
        """Transforme les utilisateurs sélectionnés en Administrateur"""
        count = queryset.update(role="ADMIN", grade=None, updated_at=timezone.now())
        self.message_user(
            request,
            f"{count} utilisateur(s) transformé(s) en Administrateur.",
        )

    set_admin.short_description = "Passer en Administrateur"

    def set_commercial(self, request, queryset):
        """Transforme les utilisateurs sélectionnés en Commercial"""
        count = queryset.update(
            role="COMMERCIAL",
            grade=None,
            is_staff=True,
            updated_at=timezone.now()
        )
        self.message_user(
            request,
            f"{count} utilisateur(s) transformé(s) en Commercial.",
        )

    set_commercial.short_description = "Passer en Commercial"

    def set_apporteur_freemium(self, request, queryset):
        """Transforme les utilisateurs sélectionnés en Apporteur Freemium"""
        count = queryset.update(
            role="APPORTEUR",
            grade="FREEMIUM",
            updated_at=timezone.now()
        )
        self.message_user(
            request,
            f"{count} utilisateur(s) transformé(s) en Apporteur Freemium.",
        )

    set_apporteur_freemium.short_description = "Passer en Apporteur (Freemium)"

    def set_apporteur_platine(self, request, queryset):
        """Transforme les utilisateurs sélectionnés en Apporteur Platine"""
        count = queryset.update(
            role="APPORTEUR",
            grade="PLATINE",
            updated_at=timezone.now()
        )
        self.message_user(
            request,
            f"{count} utilisateur(s) transformé(s) en Apporteur Platine.",
        )

    set_apporteur_platine.short_description = "Passer en Apporteur (Platine)"

    def reset_grade(self, request, queryset):
        """Réinitialise le grade des utilisateurs sélectionnés"""
        count = queryset.update(grade=None, updated_at=timezone.now())
        self.message_user(
            request,
            f"{count} utilisateur(s) réinitialisé(s) (grade supprimé).",
        )

    reset_grade.short_description = "Réinitialiser le grade"

    def get_fieldsets(self, request, obj=None):
        """Masque le champ grade pour les ADMIN et COMMERCIAL"""
        fieldsets = super().get_fieldsets(request, obj)

        if obj and obj.role in ["ADMIN", "COMMERCIAL"]:
            new_fieldsets = list(fieldsets)
            for i, (title, options) in enumerate(new_fieldsets):
                if title == _("Grade (apporteur uniquement)"):
                    new_fieldsets.pop(i)
                    break
            return tuple(new_fieldsets)

        return fieldsets