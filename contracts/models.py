from django.db import models
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q, Manager
from decimal import Decimal
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from contracts.referentiels import MARQUES, CATEGORIES, CARBURANTS
from django.utils import timezone


# =========================
# Client
# =========================
class Client(models.Model):
    """Modèle Client"""
    phone_regex = RegexValidator(
        regex=r'^(70|71|75|76|77|78|30|33|34)\d{7}$',
        message="Le numéro doit être au format sénégalais (70,71,75,76,77,78,30,33,34)"
    )
    prenom = models.CharField(max_length=100, verbose_name='Prénom')
    nom = models.CharField(max_length=100, verbose_name='Nom')
    telephone = models.CharField(
        validators=[phone_regex],
        max_length=9,
        unique=True,
        verbose_name='Téléphone'
    )
    adresse = models.TextField(verbose_name='Adresse')
    email = models.EmailField(blank=True, null=True, verbose_name='Email')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='clients_created',
        verbose_name='Créé par'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Date de création')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Dernière modification')
    code_askia = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        unique=True,
        verbose_name='Code Client ASKIA'
    )

    class Meta:
        verbose_name = 'Client'
        verbose_name_plural = 'Clients'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.prenom} {self.nom} - {self.telephone}"

    @property
    def nom_complet(self):
        return f"{self.prenom} {self.nom}"


# =========================
# Véhicule
# =========================
class Vehicule(models.Model):
    """Modèle Véhicule"""

    immat_validators = [
        RegexValidator(
            regex=(
                r'^('
                r'(AB|AC|DK|TH|SL|DB|LG|TC|KL|KD|ZG|FK|KF|KG|MT|SD)-?\d{4}-?[A-Z]{1,2}'
                r'|'
                r'[A-Z]{2}-?\d{3}-?[A-Z]{2}'
                r'|'
                r'AD-?\d{4}'
                r'|'
                r'\d{4}-?EX'
                r'|'
                r'\d{4}-?EP\d{2}'
                r'|'
                r'\d{3}-?AP-?\d{4}'
                r'|'
                r'\d{4}-?TT-?[A-Z]'
                r'|'
                r'AD\d{4}-?TT-?[A-Z]'
                r'|'
                r'CH-?\d{6}'
                r')$'
            ),
            message=(
                "Format d'immatriculation invalide. Formats acceptés : "
                "Régional (DK-0001-BB), Ancien (AA-001-AA), Diplomatique (AD-0001), "
                "Export (0001EX, 0001EP01), Apporteur (001AP0001), "
                "Transport temporaire (0001-TT-A, AD0001TTA), Étranger (CH-000001)"
            )
        )
    ]

    immatriculation = models.CharField(
        max_length=20,
        unique=True,
        validators=immat_validators,
        verbose_name='Immatriculation',
        help_text="Formats valides : DK-0000-H, DK-0000-HA, AA-001-AA, AD-0001, 0001EX, 0001EP01, 001AP0001, 0001-TT-A, CH-000001"
    )
    marque = models.CharField(max_length=10, choices=MARQUES, verbose_name='Marque')
    modele = models.CharField(max_length=100, verbose_name='Modèle')
    categorie = models.CharField(max_length=3, choices=CATEGORIES, verbose_name='Catégorie')
    sous_categorie = models.CharField(
        max_length=3, blank=True, null=True, verbose_name='Sous-catégorie',
        help_text='Obligatoire pour les TPC (catégorie 520) ou 2 Roues (550)'
    )
    charge_utile = models.IntegerField(
        blank=True, null=True, validators=[MinValueValidator(0)],
        verbose_name='Charge utile (kg)', help_text='Obligatoire pour les TPC (catégorie 520)'
    )
    puissance_fiscale = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(50)],
        verbose_name='Puissance fiscale (CV)'
    )
    nombre_places = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        verbose_name='Nombre de places'
    )
    carburant = models.CharField(max_length=6, choices=CARBURANTS, verbose_name='Type de carburant')
    valeur_neuve = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        validators=[MinValueValidator(0)], verbose_name='Valeur à neuf',
        help_text='Valeur du véhicule neuf en FCFA'
    )
    valeur_venale = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        validators=[MinValueValidator(0)], verbose_name='Valeur vénale',
        help_text='Valeur actuelle du véhicule en FCFA'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Date de création')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Dernière modification')

    class Meta:
        verbose_name = 'Véhicule'
        verbose_name_plural = 'Véhicules'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['immatriculation']),
            models.Index(fields=['marque', 'modele']),
            models.Index(fields=['categorie']),
        ]
        constraints = [
            models.CheckConstraint(
                check=~Q(valeur_neuve__lt=0) & ~Q(valeur_venale__lt=0),
                name="vehicule_valeurs_non_negatives"
            ),
        ]

    @staticmethod
    def normalize_immat(immat: str) -> str:
        """Uppercase + suppression espaces/tirets."""
        if not immat:
            return ""
        return immat.upper().replace(" ", "").replace("-", "").strip()

    def __str__(self):
        return f"{self.immatriculation_formatted} - {self.get_marque_display()} {self.modele}"

    def clean(self):
        errors = {}

        # Normalisation + validation immatriculation
        if self.immatriculation:
            raw = self.immatriculation
            immat_normalized = Vehicule.normalize_immat(raw)
            validator = self.immat_validators[0]
            try:
                validator(immat_normalized)
            except ValidationError as e:
                errors['immatriculation'] = [f"Format invalide : '{raw}'. {e.message}"]
            else:
                # Stockage sans tirets
                self.immatriculation = immat_normalized

        # Règles par catégorie
        if self.categorie == "520":
            if not self.sous_categorie:
                errors.setdefault('sous_categorie', []).append(
                    "La sous-catégorie est obligatoire pour les véhicules TPC (catégorie 520)"
                )
            if not self.charge_utile or self.charge_utile <= 0:
                errors.setdefault('charge_utile', []).append(
                    "La charge utile doit être renseignée et supérieure à 0 pour les TPC"
                )
        elif self.categorie == "550":
            if not self.sous_categorie:
                errors.setdefault('sous_categorie', []).append(
                    "Le genre est obligatoire pour les 2 Roues (catégorie 550)"
                )

        # Nettoyage modèle + comparaison valeurs
        if self.modele:
            self.modele = self.modele.strip().upper()
        if self.valeur_venale and self.valeur_neuve and self.valeur_venale > self.valeur_neuve:
            errors['valeur_venale'] = ["La valeur vénale ne peut pas être supérieure à la valeur à neuf"]

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Validation systématique
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def immatriculation_formatted(self) -> str:
        """Formate l’immatriculation à l’affichage depuis la valeur stockée sans tirets."""
        if not self.immatriculation:
            return ""
        immat = self.immatriculation.upper()

        # Régional: DK0000H ou DK0000HA
        if len(immat) >= 8 and immat[:2] in [
            'AB', 'AC', 'DK', 'TH', 'SL', 'DB', 'LG', 'TC', 'KL', 'KD', 'ZG', 'FK', 'KF', 'KG', 'MT', 'SD'
        ] and immat[2:6].isdigit() and immat[6:].isalpha():
            return f"{immat[:2]}-{immat[2:6]}-{immat[6:]}"

        # Ancien: AA001AA
        if len(immat) == 7 and immat[:2].isalpha() and immat[2:5].isdigit() and immat[5:].isalpha():
            return f"{immat[:2]}-{immat[2:5]}-{immat[5:]}"

        # Diplomatique: AD0001
        if immat.startswith('AD') and len(immat) == 6 and immat[2:].isdigit():
            return f"AD-{immat[2:]}"

        # Export: 0001EX
        if len(immat) == 6 and immat[:4].isdigit() and immat.endswith('EX'):
            return f"{immat[:4]}-EX"

        # EP: 0001EP01
        if len(immat) == 8 and immat[:4].isdigit() and immat[4:6] == 'EP' and immat[6:].isdigit():
            return f"{immat[:4]}-{immat[4:]}"

        # Apporteur: 001AP0001
        if len(immat) == 9 and immat[:3].isdigit() and immat[3:5] == 'AP' and immat[5:].isdigit():
            return f"{immat[:3]}-AP-{immat[5:]}"

        # TT: 0001TTA ou AD0001TTA
        if 'TT' in immat and len(immat) >= 7:
            if immat.startswith('AD') and len(immat) == 8:
                return f"{immat[:6]}-TT-{immat[-1]}"
            if len(immat) == 7 and immat[:4].isdigit():
                return f"{immat[:4]}-TT-{immat[-1]}"

        # Étranger: CH000001
        if immat.startswith('CH') and len(immat) == 8 and immat[2:].isdigit():
            return f"CH-{immat[2:]}"

        return immat

    def get_marque_display(self):
        # Fallback au cas où le code n’est pas dans MARQUES
        return dict(MARQUES).get(self.marque, self.marque)

    def get_categorie_display(self):
        return dict(CATEGORIES).get(self.categorie, self.categorie)


# =========================
# Contrat
# =========================
class ContratQuerySet(models.QuerySet):
    def emis_avec_doc(self):
        """Contrats valides (émis/actifs/expirés) avec au moins un document."""
        return self.filter(
            status__in=["EMIS", "ACTIF", "EXPIRE"]
        ).filter(
            (Q(link_attestation__isnull=False) & ~Q(link_attestation="")) |
            (Q(link_carte_brune__isnull=False) & ~Q(link_carte_brune=""))
        )

    def due_today(self):
        """Contrats arrivant à échéance aujourd'hui."""
        return self.filter(date_echeance=timezone.now().date())


class ContratManager(Manager):
    def get_queryset(self):
        return ContratQuerySet(self.model, using=self._db)

    def emis_avec_doc(self):
        """Contrats valides (émis/actifs/expirés) avec au moins un document."""
        # Expiration auto des anciens contrats encore en EMIS/ACTIF
        self.get_queryset().filter(
            status__in=['EMIS', 'ACTIF'],
            date_echeance__lt=date.today()
        ).update(status='EXPIRE')
        return self.get_queryset().emis_avec_doc()

    def due_today(self):
        """Contrats arrivant à échéance aujourd'hui."""
        return self.get_queryset().due_today()


class Contrat(models.Model):
    """Modèle Contrat d'assurance"""

    DUREE_CHOICES = [
        (1, '1 mois'),
        (2, '2 mois'),
        (3, '3 mois'),
        (6, '6 mois'),
        (12, '12 mois'),
    ]

    STATUS_CHOICES = [
        ('SIMULATION', 'Simulation'),
        ('EMIS', 'Émis'),
        ('ACTIF', 'Actif'),
        ('EXPIRE', 'Expiré'),
        ('ANNULE', 'Annulé (Complet)'),
        ('ANNULE_LOCAL', 'Annulé (Local uniquement - API à réessayer)'),
    ]

    # Relations
    client = models.ForeignKey(
        "contracts.Client",
        on_delete=models.PROTECT,
        related_name='contrats',
        verbose_name='Client'
    )
    vehicule = models.ForeignKey(
        "contracts.Vehicule",
        on_delete=models.PROTECT,
        related_name='contrats',
        verbose_name='Véhicule'
    )
    apporteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='contrats_apportes',
        verbose_name='Apporteur'
    )

    # Informations du contrat
    numero_police = models.CharField(max_length=50, unique=True, blank=True, null=True)
    numero_facture = models.CharField(max_length=50, blank=True, null=True, verbose_name='N° Facture Askia')
    date_effet = models.DateField()
    duree = models.PositiveIntegerField(choices=DUREE_CHOICES, default=12)
    date_echeance = models.DateField(blank=True, null=True)
    type_garantie = models.CharField(max_length=100, default='Responsabilité Civile', verbose_name='Type de Garantie')

    # Tarification
    prime_nette = models.DecimalField(max_digits=10, decimal_places=2)
    accessoires = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fga = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    taxes = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    prime_ttc = models.DecimalField(max_digits=10, decimal_places=2)

    # NOUVELLE LOGIQUE COMMISSION
    commission_askia = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                           verbose_name="Commission BWHITE (Total)")
    commission_apporteur = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    commission_bwhite = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                            verbose_name='Commission BWHITE (Profit)')
    net_a_reverser = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                         verbose_name="Net à reverser (à Askia)")

    # Statut
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='EMIS')

    # Données API
    askia_response = models.JSONField(blank=True, null=True)
    id_saisie_askia = models.CharField(max_length=100, blank=True, null=True)

    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    emis_at = models.DateTimeField(blank=True, null=True)

    # Documents
    link_attestation = models.URLField(null=True, blank=True)
    link_carte_brune = models.URLField(null=True, blank=True)

    # Champs d'annulation
    annule_at = models.DateTimeField(blank=True, null=True, verbose_name="Date d'annulation")
    annule_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contrats_annules',
        verbose_name='Annulé par'
    )
    annule_raison = models.CharField(max_length=255, blank=True, verbose_name="Raison d'annulation")

    # Manager custom
    objects = ContratManager()

    class Meta:
        verbose_name = 'Contrat'
        verbose_name_plural = 'Contrats'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['numero_police']),
            models.Index(fields=['status']),
            models.Index(fields=['date_effet']),
            models.Index(fields=['date_echeance']),
            models.Index(fields=['apporteur']),
        ]
        constraints = [
            models.CheckConstraint(check=Q(prime_nette__gte=0), name="prime_nette_non_negative"),
            models.CheckConstraint(check=Q(prime_ttc__gte=0), name="prime_ttc_non_negative"),
        ]

    def __str__(self):
        return f"{self.numero_police or 'SIMULATION'} - {self.client.nom_complet}"

    def clean(self):
        """Validation métier."""
        if not self.date_effet:
            raise ValidationError("Un contrat doit avoir une date d'effet.")

    def calculate_commission(self):
        """
        Calcule TOUTES les commissions (Askia, Apporteur, BWHITE) et le Net à Reverser.
        """
        # Constantes paramétrables avec valeurs par défaut sûres
        ASKIA_TAUX = Decimal(str(getattr(settings, 'COMMISSION_ASKIA_TAUX', '0.20')))
        ASKIA_ACCESSOIRES = Decimal(str(getattr(settings, 'COMMISSION_ASKIA_FIXE', '3000')))

        PL_TAUX = Decimal(str(getattr(settings, 'COMMISSION_PLATINE_TAUX', '0.18')))
        PL_FIXE = Decimal(str(getattr(settings, 'COMMISSION_PLATINE_FIXE', '2000')))

        FR_TAUX = Decimal(str(getattr(settings, 'COMMISSION_FREEMIUM_TAUX', '0.10')))
        FR_FIXE = Decimal(str(getattr(settings, 'COMMISSION_FREEMIUM_FIXE', '1800')))

        # 1. Commission totale versée par Askia à BWHITE
        self.commission_askia = (self.prime_nette * ASKIA_TAUX) + ASKIA_ACCESSOIRES

        # 2. Commission Apporteur
        self.commission_apporteur = Decimal("0.00")
        if self.apporteur and getattr(self.apporteur, "role", None) == 'APPORTEUR':
            grade = getattr(self.apporteur, "grade", None)
            if grade == 'PLATINE':
                self.commission_apporteur = (self.prime_nette * PL_TAUX) + PL_FIXE
            elif grade == 'FREEMIUM':
                self.commission_apporteur = (self.prime_nette * FR_TAUX) + FR_FIXE

        # 3. Commission BWHITE (Profit)
        self.commission_bwhite = self.commission_askia - self.commission_apporteur

        # 4. Net à reverser (ce que BWHITE doit à ASKIA)
        self.net_a_reverser = self.prime_ttc - self.commission_askia

    def calculate_date_echeance(self):
        """Calcule la date d'échéance basée sur la date d'effet et la durée."""
        if self.date_effet and self.duree:
            self.date_echeance = self.date_effet + relativedelta(months=self.duree) - timedelta(days=1)

    def save(self, *args, **kwargs):
        """Sauvegarde avec calculs automatiques et horodatage."""
        if not self.date_echeance:
            self.calculate_date_echeance()

        # Recalcule toujours les commissions pour éviter les incohérences après modification.
        self.calculate_commission()

        # Set emis_at si transition ou création en statut EMIS
        if self.status == 'EMIS' and self.emis_at is None:
            self.emis_at = timezone.now()

        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_actif(self):
        """Contrat actif à la date du jour."""
        today = date.today()
        return self.status in ['EMIS', 'ACTIF'] and self.date_effet <= today <= (self.date_echeance or today)

    @property
    def is_expire(self):
        """Contrat expiré."""
        if not self.date_echeance:
            return False
        return date.today() > self.date_echeance

    @property
    def is_valide(self):
        """Contrat émis/actif/expiré avec au moins un document."""
        return self.status in ['EMIS', 'ACTIF', 'EXPIRE'] and (self.link_attestation or self.link_carte_brune)

    @property
    def raison_invalide(self):
        """Raison d’invalidité si applicable."""
        if self.status not in ['EMIS', 'ACTIF', 'EXPIRE']:
            return f"Statut: {self.get_status_display()}"
        if not (self.link_attestation or self.link_carte_brune):
            return "Aucun document (attestation/carte brune)"
        return None

    @property
    def attestation_url(self):
        return (self.link_attestation or "").strip()

    @property
    def carte_brune_url(self):
        return (self.link_carte_brune or "").strip()
