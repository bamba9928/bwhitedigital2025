from django.contrib.auth.models import AbstractUser
from django.db import models

from contracts.validators import SENEGAL_PHONE_VALIDATOR


class User(AbstractUser):
    ROLE_CHOICES = [("ADMIN", "Administrateur"), ("APPORTEUR", "Apporteur d'affaires")]
    GRADE_CHOICES = [
        ("PLATINE", "Platine - 18% + 2000 FCFA"),
        ("FREEMIUM", "Freemium - 10% + 1800 FCFA"),
    ]

    role = models.CharField(
        max_length=10, choices=ROLE_CHOICES, default="APPORTEUR", verbose_name="Rôle"
    )
    grade = models.CharField(
        max_length=10,
        choices=GRADE_CHOICES,
        blank=True,
        null=True,
        verbose_name="Grade",
        help_text="Applicable uniquement pour les apporteurs",
    )

    # 9 chiffres normalisés, unique + index
    phone = models.CharField(
        validators=[SENEGAL_PHONE_VALIDATOR],
        max_length=9,
        unique=True,
        db_index=True,
        verbose_name="Téléphone",
    )

    address = models.TextField(blank=True, verbose_name="Adresse")
    created_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_users",
        verbose_name="Créé par",
    )
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Date de création"
    )
    updated_at = models.DateTimeField(
        auto_now=True, verbose_name="Dernière modification"
    )

    class Meta:
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"
        ordering = ["-created_at"]

    def __str__(self):
        label = self.get_full_name() or self.username
        if self.role == "ADMIN":
            return "{label} (Administrateur)"
        grade_display = self.get_grade_display() if self.grade else "Sans grade"
        return "{label} ({grade_display})"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.username

    @property
    def is_admin(self):
        return self.role == "ADMIN"

    @property
    def is_apporteur(self):
        return self.role == "APPORTEUR"

    def save(self, *args, **kwargs):
        # normaliser phone en 9 chiffres
        if self.phone:
            self.phone = "".join(filter(str.isdigit, self.phone))[:9]

        # cohérence staff/superuser/role
        if self.is_superuser:
            self.role = "ADMIN"
            self.is_staff = True
            self.grade = None
        elif self.role == "ADMIN":
            self.is_staff = True
            self.grade = None
        elif self.role == "APPORTEUR" and not self.grade:
            self.grade = "FREEMIUM"
        super().save(*args, **kwargs)
