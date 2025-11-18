"""
BWHITE DIGITAL — Django settings

Projet : Plateforme d’assurance BWHITE DIGITAL
Version : V1.01
Auteur : Mouhamadou Bamba DIENG
Contact : +221 77 249 05 30 • bigrip2016@gmail.com 2025

Notes :
- Configurez via les variables d’environnement (SECRET_KEY, DEBUG, ALLOWED_HOSTS, DB…).
- Ne stockez jamais de secrets en dur dans le dépôt.
- Utilisez des fichiers .env séparés pour dev / staging / prod.
- Réglez DJANGO_SETTINGS_MODULE pour cibler le bon module de settings.
"""

import os
from decimal import Decimal
from pathlib import Path

from decouple import config, Csv
from django.contrib.messages import constants as messages
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
# ==============================
# Sécurité
# ==============================
SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost", cast=Csv())

# ==============================
# Applications
# ==============================
INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "widget_tweaks",
    "django_htmx",
    "django.contrib.humanize",
    "accounts.apps.AccountsConfig",
    "contracts.apps.ContractsConfig",
    "payments.apps.PaymentsConfig",
    "dashboard.apps.DashboardConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "askia_insurance.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "askia_insurance.wsgi.application"

# ==============================
# Base de données
# ==============================
DB_ENGINE = os.getenv("DB_ENGINE", "django.db.backends.sqlite3").strip()
DB_NAME = os.getenv("DB_NAME", "").strip()
DB_USER = os.getenv("DB_USER", "").strip()
DB_PWD = os.getenv("DB_PASSWORD", "").strip()
DB_HOST = os.getenv("DB_HOST", "").strip()
DB_PORT = os.getenv("DB_PORT", "").strip()

if DB_ENGINE == "django.db.backends.sqlite3":
    # Toujours un chemin absolu
    NAME = str((BASE_DIR / (DB_NAME or "db.sqlite3")).resolve())
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": NAME,
        }
    }
else:
    # PostgreSQL
    if not (DB_NAME and DB_USER):
        raise RuntimeError("DB_NAME et DB_USER requis pour PostgreSQL")
    DATABASES = {
        "default": {
            "ENGINE": DB_ENGINE,
            "NAME": DB_NAME,
            "USER": DB_USER,
            "PASSWORD": DB_PWD,
            "HOST": DB_HOST or "127.0.0.1",
            "PORT": DB_PORT or "5432",
            "CONN_MAX_AGE": 60,
        }
    }
# ==============================
# Authentification
# ==============================
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:login"

# ==============================
# Internationalisation
# ==============================
LANGUAGE_CODE = "fr-FR"
TIME_ZONE = "Africa/Dakar"
USE_I18N = True
USE_TZ = True

# ==============================
# Fichiers statiques et médias
# ==============================
# ==========================
# 🔒 CONFIGURATION SSL / COOKIES (ACTIVER EN PROD SEULEMENT)
# ==========================
# ⚠️ Active uniquement si le site est servi en HTTPS (production)
# Décommentez ces lignes en production
# if not DEBUG:
#     SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https)
#     CSRF_COOKIE_SECURE = True
#     SESSION_COOKIE_SECURE = True
#     SECURE_CONTENT_TYPE_NOSNIFF = True
#     SECURE_SSL_REDIRECT = True
#     SECURE_HSTS_SECONDS = 31536000
#     SECURE_HSTS_INCLUDE_SUBDOMAINS = True
#     SECURE_HSTS_PRELOAD = True

# storage staticfiles pour Whitenoise
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
    },
}
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ==============================
# ASKIA API
# ==============================
ASKIA_BASE_URL = config("ASKIA_BASE_URL")
ASKIA_APP_CLIENT = config("ASKIA_APP_CLIENT")
ASKIA_PV_CODE = config("ASKIA_PV_CODE")
ASKIA_BR_CODE = config("ASKIA_BR_CODE")

# ==============================
# Email
# ==============================
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL", default="Bwhite Assurance <no-reply@bwhite.com>"
)

# ==============================
# Messages (Bootstrap mapping)
# ==============================
MESSAGE_TAGS = {
    messages.DEBUG: "debug",
    messages.INFO: "info",
    messages.SUCCESS: "success",
    messages.WARNING: "warning",
    messages.ERROR: "danger",
}

# ==============================
# Logs
# ==============================
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "contracts.log"),
            "formatter": "verbose",
            "maxBytes": 5_000_000,
            "backupCount": 3,
        },
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "contracts": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "contracts.api_client": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "bwhite.contracts": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
# ==========================
# ⚙️ CONFIGURATION DES SESSIONS
# ==========================

# Durée max d’inactivité avant expiration (10 minutes = 600s)
# SESSION_COOKIE_AGE = 600

# Renouvelle le compteur de session à chaque requête (inactivité réelle)
# SESSION_SAVE_EVERY_REQUEST = True

# Déconnecte l’utilisateur si le navigateur est fermé
# SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# CSRF pour domaines HTTPS (prod)
# CSRF_TRUSTED_ORIGINS = config(
#    'CSRF_TRUSTED_ORIGINS',
#    default='',
#    cast=Csv()
# )
# ==========================
# 🔒 CONFIGURATION SSL / COOKIES (ACTIVER EN PROD SEULEMENT)
# ==========================
# ⚠️ Active uniquement si le site est servi en HTTPS (production)
# if not DEBUG:
# SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
# CSRF_COOKIE_SECURE = True
# SESSION_COOKIE_SECURE = True
# SECURE_CONTENT_TYPE_NOSNIFF = True
# SECURE_SSL_REDIRECT = True
# SECURE_HSTS_SECONDS = 31536000
# SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# SECURE_HSTS_PRELOAD = True
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-snowflake",
    }
}
# ==============================
# COMMISSIONS & TARIFS
# ==============================
# Taux Askia (fixe)
COMMISSION_ASKIA_TAUX = config("COMMISSION_ASKIA_TAUX", default="0.20", cast=Decimal)
COMMISSION_ASKIA_FIXE = config("COMMISSION_ASKIA_FIXE", default="3000", cast=Decimal)

# Taux Apporteurs
COMMISSION_PLATINE_TAUX = config(
    "COMMISSION_PLATINE_TAUX", default="0.18", cast=Decimal
)
COMMISSION_PLATINE_FIXE = config(
    "COMMISSION_PLATINE_FIXE", default="2000", cast=Decimal
)

COMMISSION_FREEMIUM_TAUX = config(
    "COMMISSION_FREEMIUM_TAUX", default="0.10", cast=Decimal
)
COMMISSION_FREEMIUM_FIXE = config(
    "COMMISSION_FREEMIUM_FIXE", default="1800", cast=Decimal
)

COMMISSION_ADMIN_TAUX = COMMISSION_ASKIA_TAUX - COMMISSION_PLATINE_TAUX  # attendu 0.02
COMMISSION_ADMIN_FIXE = COMMISSION_ASKIA_FIXE - COMMISSION_PLATINE_FIXE  # attendu 1000
# Garde-fous
if COMMISSION_ADMIN_TAUX < 0 or COMMISSION_ADMIN_FIXE < 0:
    raise ValueError("Paramétrage commissions incohérent: admin < 0")

FEATURES = {
    "QUOTE_FLOW": True,
    "DEADLINES": True,
    "ASKIA_DOCS": True,
    "BANNER": True,
    "BROKER_ONBOARDING": True,
    "TWO_WHEELS": True,
}
BUSINESS = {
    "SERVICE_PHONE": "780103636",
}
# ==============================
# Configuration JAZZMIN
# ==============================
JAZZMIN_SETTINGS = {
    # Titre de la fenêtre (onglet du navigateur)
    "site_title": "BWHITE Admin",

    # Titre sur l'écran de connexion (peut être long)
    "site_header": "BWHITE DIGITAL",

    # Titre court dans la barre de navigation (logo)
    "site_brand": "BWHITE Admin",

    # Logo pour l'écran de connexion
    "login_logo": "images/logo.png",  # Doit être dans /static/
    "login_logo_dark": "images/logo.png",

    # Logo pour la barre de navigation
    "site_logo": "images/logo.png",

    # Thème
    "theme": "darkly",  # Un thème sombre populaire qui ira bien

    # Options UI
    "show_ui_builder": True,  # Permet de tester les thèmes en direct

    "topmenu_links": [
        # Lien vers le site principal
        {"name": "Accueil", "url": "dashboard:home", "permissions": ["auth.view_user"]},
        # Modèle (exemple)
        {"model": "accounts.User"},
    ],

    "icons": {
        "auth.User": "fas fa-users-cog",
        "accounts.User": "fas fa-users",
        "accounts.ApporteurOnboarding": "fas fa-id-card",
        "contracts.Contrat": "fas fa-file-signature",
        "contracts.Client": "fas fa-user-tie",
        "contracts.Vehicule": "fas fa-car",
        "payments.PaiementApporteur": "fas fa-money-check-alt",
        "payments.HistoriquePaiement": "fas fa-history",
    },

    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-dot-circle",
}