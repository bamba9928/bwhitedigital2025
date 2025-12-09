"""
BWHITE DIGITAL — Django settings
Version : V1.01
"""

import os
from decimal import Decimal
from pathlib import Path
from decouple import Csv, config
from django.core.exceptions import ImproperlyConfigured
from django.contrib.messages import constants as messages
from dotenv import load_dotenv

# ==============================
# BASE
# ==============================
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
    "django.contrib.humanize",

    # Libs tierces
    "widget_tweaks",
    "django_htmx",

    # Vos apps
    "accounts.apps.AccountsConfig",
    "contracts.apps.ContractsConfig",
    "payments.apps.PaymentsConfig",
    "dashboard.apps.DashboardConfig",
]

# ==============================
# Middleware
# ==============================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
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
DB_ENGINE = config("DB_ENGINE", default="django.db.backends.sqlite3").strip()
DB_NAME = config("DB_NAME", default="db.sqlite3").strip()
DB_USER = config("DB_USER", default="").strip()
DB_PWD = config("DB_PASSWORD", default="").strip()
DB_HOST = config("DB_HOST", default="").strip()
DB_PORT = config("DB_PORT", default="").strip()

if DB_ENGINE == "django.db.backends.sqlite3":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str((BASE_DIR / DB_NAME).resolve()),
        }
    }
else:
    # PostgreSQL configuration
    DATABASES = {
        "default": {
            "ENGINE": DB_ENGINE,
            "NAME": DB_NAME,
            "USER": DB_USER,
            "PASSWORD": DB_PWD,
            "HOST": DB_HOST or "127.0.0.1",
            "PORT": DB_PORT or "5432",
            "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=60, cast=int),
        }
    }

# ==============================
# Authentification
# ==============================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:login"

# ==============================
# I18N / L10N
# ==============================
LANGUAGE_CODE = "fr-FR"
TIME_ZONE = "Africa/Dakar"
USE_I18N = True
USE_TZ = True

# ==============================
# Static / Media
# ==============================
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ==============================
# Email
# ==============================
EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="Bwhite Assurance <no-reply@bwhite.com>")

MESSAGE_TAGS = {
    messages.DEBUG: "debug",
    messages.INFO: "info",
    messages.SUCCESS: "success",
    messages.WARNING: "warning",
    messages.ERROR: "danger",
}

# ==============================
# Logs (AJOUT PAYMENTS)
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
            "filename": str(LOG_DIR / "bwhite.log"),
            "formatter": "verbose",
            "maxBytes": 5_000_000,
            "backupCount": 3,
        },
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        # Vos apps existantes
        "contracts": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
        "bwhite.contracts": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},


        "payments": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False
        },
    },
}

# ==============================
# ASKIA / Business
# ==============================
ASKIA_BASE_URL = config("ASKIA_BASE_URL")
ASKIA_APP_CLIENT = config("ASKIA_APP_CLIENT")
ASKIA_PV_CODE = config("ASKIA_PV_CODE")
ASKIA_BR_CODE = config("ASKIA_BR_CODE")

COMMISSION_ASKIA_TAUX = config("COMMISSION_ASKIA_TAUX", default="0.20", cast=Decimal)
COMMISSION_ASKIA_FIXE = config("COMMISSION_ASKIA_FIXE", default="3000", cast=Decimal)
COMMISSION_PLATINE_TAUX = config("COMMISSION_PLATINE_TAUX", default="0.18", cast=Decimal)
COMMISSION_PLATINE_FIXE = config("COMMISSION_PLATINE_FIXE", default="2000", cast=Decimal)
COMMISSION_FREEMIUM_TAUX = config("COMMISSION_FREEMIUM_TAUX", default="0.10", cast=Decimal)
COMMISSION_FREEMIUM_FIXE = config("COMMISSION_FREEMIUM_FIXE", default="1800", cast=Decimal)

COMMISSION_ADMIN_TAUX = COMMISSION_ASKIA_TAUX - COMMISSION_PLATINE_TAUX
COMMISSION_ADMIN_FIXE = COMMISSION_ASKIA_FIXE - COMMISSION_PLATINE_FIXE

FEATURES = {
    "QUOTE_FLOW": True,
    "DEADLINES": True,
    "ASKIA_DOCS": True,
    "BANNER": True,
    "BROKER_ONBOARDING": True,
    "TWO_WHEELS": True,
}

BUSINESS = {
    "SERVICE_PHONE": config("SERVICE_PHONE", default="770000000"),
}
# ==============================
# BICTORYS
# ==============================
BICTORYS_BASE_URL = config("BICTORYS_BASE_URL", default="https://api.bictorys.com")
BICTORYS_PUBLIC_KEY = config("BICTORYS_PUBLIC_KEY")
BICTORYS_SECRET_KEY = config("BICTORYS_SECRET_KEY")
BICTORYS_WEBHOOK_SECRET = config("BICTORYS_WEBHOOK_SECRET", default="")
BICTORYS_TIMEOUT = config("BICTORYS_TIMEOUT", default=30, cast=int)

# ==============================
# JAZZMIN
# ==============================
JAZZMIN_SETTINGS = {
    "site_title": "BWHITE Admin",
    "site_header": "BWHITE DIGITAL",
    "site_brand": "BWHITE Admin",
    "login_logo": "images/logo.png",
    "login_logo_dark": "images/logo.png",
    "site_logo": "images/logo.png",
    "theme": "darkly",
    "show_ui_builder": True,
    "topmenu_links": [
        {"name": "Accueil", "url": "dashboard:home", "permissions": ["auth.view_user"]},
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