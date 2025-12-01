from django.contrib.auth.models import AbstractUser
from django.db import models

from contracts.validators import SENEGAL_PHONE_VALIDATOR


class User(AbstractUser):
    """Modèle utilisateur personnalisé avec gestion des rôles et grades"""

    ROLE_CHOICES = [
        ("ADMIN", "Administrateur"),
        ("COMMERCIAL", "Commercial"),
        ("APPORTEUR", "Apporteur d'affaires"),
    ]
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
        """Représentation textuelle de l'utilisateur avec rôle/grade"""
        label = self.get_full_name() or self.username
        if self.role == "ADMIN":
            return f"{label} (Administrateur)"
        if self.role == "COMMERCIAL":
            return f"{label} (Commercial)"
        grade_display = self.get_grade_display() if self.grade else "Sans grade"
        return f"{label} ({grade_display})"

    def get_full_name(self):
        """Retourne le nom complet ou le username si vide"""
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name if full_name else self.username

    @property
    def is_admin(self):
        """Vérifie si l'utilisateur est administrateur"""
        return self.role == "ADMIN"

    @property
    def is_commercial(self):
        """Vérifie si l'utilisateur est commercial"""
        return self.role == "COMMERCIAL"

    @property
    def is_apporteur(self):
        """Vérifie si l'utilisateur est apporteur"""
        return self.role == "APPORTEUR"

    @property
    def is_true_admin(self):
        """Vrai Admin seulement (pour masquer les finances au Commercial)"""
        return self.role == "ADMIN"

    @property
    def grade_short(self):
        """Libellé court du grade (sans % / FCFA)"""
        if self.grade == "PLATINE":
            return "Platine"
        if self.grade == "FREEMIUM":
            return "Freemium"
        return None

    def save(self, *args, **kwargs):
        """Sauvegarde avec normalisation du téléphone et cohérence des permissions"""
        # Normaliser le numéro de téléphone en 9 chiffres
        if self.phone:
            self.phone = "".join(filter(str.isdigit, self.phone))[:9]

        # Assurer la cohérence entre staff/superuser/role
        if self.is_superuser:
            self.role = "ADMIN"
            self.is_staff = True
            self.grade = None
        elif self.role == "ADMIN":
            self.is_staff = True
            self.grade = None
        elif self.role == "COMMERCIAL":
            self.is_staff = True
            self.is_superuser = False
            self.grade = None
        elif self.role == "APPORTEUR":
            self.is_staff = False
            if not self.grade:
                self.grade = "FREEMIUM"

        super().save(*args, **kwargs)