from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin personnalisé pour le modèle User"""

    list_display = (
        "username", "get_full_name", "email", "role",
        "grade", "phone", "is_active", "is_staff", "is_superuser"
    )
    list_filter = ("role", "grade", "is_active", "is_staff", "is_superuser", "created_at")
    search_fields = ("username", "first_name", "last_name", "email", "phone")
    ordering = ("-created_at",)

    # Champs en lecture seule
    readonly_fields = ("created_at", "updated_at")

    # Organisation des fieldsets
    fieldsets = (
        (_("Informations générales"), {
            "fields": (
                "username", "password",
                "first_name", "last_name", "email",
                "phone", "address", "role",
            )
        }),
        (_("Grade (apporteur uniquement)"), {
            "fields": ("grade",),
            "classes": ("collapse",),
        }),
        (_("Permissions"), {
            "fields": (
                "is_active", "is_staff", "is_superuser",
                "groups", "user_permissions",
            )
        }),
        (_("Suivi"), {
            "fields": ("created_by", "created_at", "updated_at"),
        }),
    )

    # Fieldsets utilisés lors de la création d'un user
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "username", "password1", "password2",
                "first_name", "last_name", "email",
                "phone", "address", "role", "grade",
                "is_active", "is_staff", "is_superuser"
            ),
        }),
    )

    class Media:
        js = ("admin/js/user_admin.js",)

    actions = ["set_admin", "set_apporteur_freemium", "set_apporteur_platine", "reset_grade"]

    def set_admin(self, request, queryset):
        queryset.update(role="ADMIN", grade=None, updated_at=timezone.now())
        self.message_user(request, f"{queryset.count()} utilisateur(s) transformé(s) en Administrateur.")
    set_admin.short_description = "Passer en Administrateur"

    def set_apporteur_freemium(self, request, queryset):
        queryset.update(role="APPORTEUR", grade="FREEMIUM", updated_at=timezone.now())
        self.message_user(request, f"{queryset.count()} utilisateur(s) transformé(s) en Apporteur Freemium.")
    set_apporteur_freemium.short_description = "Passer en Apporteur (Freemium)"

    def set_apporteur_platine(self, request, queryset):
        queryset.update(role="APPORTEUR", grade="PLATINE", updated_at=timezone.now())
        self.message_user(request, f"{queryset.count()} utilisateur(s) transformé(s) en Apporteur Platine.")
    set_apporteur_platine.short_description = "Passer en Apporteur (Platine)"

    def reset_grade(self, request, queryset):
        queryset.update(grade=None, updated_at=timezone.now())
        self.message_user(request, f"{queryset.count()} utilisateur(s) réinitialisé(s) (grade supprimé).")
    reset_grade.short_description = "Réinitialiser le grade"


    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj and obj.role == "ADMIN":
            if "grade" in form.base_fields:
                form.base_fields.pop("grade")
        return form
