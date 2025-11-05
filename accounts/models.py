from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import RegexValidator
from django.utils import timezone
from decimal import Decimal


class User(AbstractUser):
    """Modèle utilisateur personnalisé"""

    ROLE_CHOICES = [
        ('ADMIN', 'Administrateur'),
        ('APPORTEUR', 'Apporteur d\'affaires'),
    ]

    GRADE_CHOICES = [
        ('PLATINE', 'Platine - 18% + 2000 FCFA'),
        ('FREEMIUM', 'Freemium - 10% + 1800 FCFA'),
    ]

    phone_regex = RegexValidator(
        regex=r'^(77|78|76|70|75)\d{7}$',
        message="Le numéro doit être au format sénégalais (77/78/76/70/75 suivi de 7 chiffres)"
    )

    # Champs personnalisés
    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        default='APPORTEUR',
        verbose_name='Rôle'
    )

    grade = models.CharField(
        max_length=10,
        choices=GRADE_CHOICES,
        blank=True,
        null=True,
        verbose_name='Grade',
        help_text='Applicable uniquement pour les apporteurs'
    )

    phone = models.CharField(
        validators=[phone_regex],
        max_length=12,
        unique=True,
        verbose_name='Téléphone'
    )

    address = models.TextField(
        blank=True,
        verbose_name='Adresse'
    )

    created_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_users',
        verbose_name='Créé par'
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Actif'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Date de création'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Dernière modification'
    )

    class Meta:
        verbose_name = 'Utilisateur'
        verbose_name_plural = 'Utilisateurs'
        ordering = ['-created_at']

    def __str__(self):
        label = self.get_full_name() or self.username
        if self.role == 'ADMIN':
            return f"{label} (Administrateur)"
        grade_display = self.get_grade_display() if self.grade else "Sans grade"
        return f"{label} ({grade_display})"

    def get_full_name(self):
        """Retourne le nom complet"""
        return f"{self.first_name} {self.last_name}".strip() or self.username

    # --- LOGIQUE COMMISSION SUPPRIMÉE ---
    # La logique est maintenant dans contracts/models.py

    @property
    def is_admin(self):
        """Vérifie si l'utilisateur est admin"""
        return self.role == 'ADMIN'

    @property
    def is_apporteur(self):
        """Vérifie si l'utilisateur est apporteur"""
        return self.role == 'APPORTEUR'

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = "ADMIN"
            self.grade = None
        elif self.role == "ADMIN":
            self.grade = None
        elif self.role == "APPORTEUR" and not self.grade:
            self.grade = "FREEMIUM"
        super().save(*args, **kwargs)