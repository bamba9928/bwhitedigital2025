"""
BWHITE DIGITAL — Django settings

Projet : Plateforme d’assurance BWHITE DIGITAL
Version : 2025
Auteur : Mouhamadou Bamba DIENG
Contact : +221 77 249 05 30 • bigrip2016@gmail.com

Notes :
- Configurez via les variables d’environnement (SECRET_KEY, DEBUG, ALLOWED_HOSTS, DB…).
- Ne stockez jamais de secrets en dur dans le dépôt.
- Utilisez des fichiers .env séparés pour dev / staging / prod.
- Réglez DJANGO_SETTINGS_MODULE pour cibler le bon module de settings.
"""
from pathlib import Path
from decouple import config, Csv
import os
from django.contrib.messages import constants as messages

BASE_DIR = Path(__file__).resolve().parent.parent

# ==============================
# Sécurité
# ==============================
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='').split(',')

# ==============================
# Applications
# ==============================
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'widget_tweaks',
    'django_htmx',
    'django.contrib.humanize',

    # Local apps
    'accounts.apps.AccountsConfig',
    'contracts.apps.ContractsConfig',
    'payments.apps.PaymentsConfig',
    'dashboard.apps.DashboardConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
]

ROOT_URLCONF = 'askia_insurance.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'askia_insurance.wsgi.application'

# ==============================
# Base de données
# ==============================
DATABASES = {
    'default': {
        'ENGINE': config('DB_ENGINE', default='django.db.backends.sqlite3'),
        'NAME': config('DB_NAME', default=BASE_DIR / 'db.sqlite3'),
        'USER': config('DB_USER', default=''),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default=''),
        'PORT': config('DB_PORT', default=''),
    }
}

# ==============================
# Authentification
# ==============================
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTH_USER_MODEL = 'accounts.User'

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'dashboard:home'
LOGOUT_REDIRECT_URL = 'accounts:login'

# ==============================
# Internationalisation
# ==============================
LANGUAGE_CODE = 'fr-FR'
TIME_ZONE = 'Africa/Dakar'
USE_I18N = True
USE_TZ = True

# ==============================
# Fichiers statiques et médias
# ==============================
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ==============================
# ASKIA API
# ==============================
ASKIA_BASE_URL = config('ASKIA_BASE_URL')
ASKIA_APP_CLIENT = config('ASKIA_APP_CLIENT')
ASKIA_PV_CODE = config('ASKIA_PV_CODE')
ASKIA_BR_CODE = config('ASKIA_BR_CODE')

# ==============================
# Email
# ==============================
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = config('EMAIL_HOST', default='')
EMAIL_PORT = config('EMAIL_PORT', default=0, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='Bwhite Assurance <no-reply@bwhite.com>')

# ==============================
# Messages (Bootstrap mapping)
# ==============================
MESSAGE_TAGS = {
    messages.DEBUG: 'debug',
    messages.INFO: 'info',
    messages.SUCCESS: 'success',
    messages.WARNING: 'warning',
    messages.ERROR: 'danger',
}

# ==============================
# Logs
# ==============================
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
                    'datefmt': '%Y-%m-%d %H:%M:%S'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'verbose'},
        'file': {'class': 'logging.FileHandler', 'filename': LOG_DIR / 'contracts.log', 'formatter': 'verbose'},
    },
    'root': {'handlers': ['console'], 'level': 'WARNING'},
    'loggers': {
            'django': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
            'django.request': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
            'contracts': {'handlers': ['console', 'file'], 'level': 'INFO', 'propagate': False},
            'contracts.api_client': {'handlers': ['console', 'file'], 'level': 'INFO', 'propagate': False},
            'bwhite.contracts': {'handlers': ['console', 'file'], 'level': 'INFO', 'propagate': False},
        },
}
# ==========================
# ⚙️ CONFIGURATION DES SESSIONS
# ==========================

# Durée max d’inactivité avant expiration (10 minutes = 600s)
#SESSION_COOKIE_AGE = 600

# Renouvelle le compteur de session à chaque requête (inactivité réelle)
#SESSION_SAVE_EVERY_REQUEST = True

# Déconnecte l’utilisateur si le navigateur est fermé
#SESSION_EXPIRE_AT_BROWSER_CLOSE = True


# ==========================
# 🔒 CONFIGURATION SSL / COOKIES (ACTIVER EN PROD SEULEMENT)
# ==========================

# ⚠️ Active uniquement si le site est servi en HTTPS (production)
# CSRF_COOKIE_SECURE = True          # Le cookie CSRF est transmis seulement via HTTPS
# SESSION_COOKIE_SECURE = True       # Le cookie de session est transmis seulement via HTTPS
# SECURE_BROWSER_XSS_FILTER = True   # Active la protection XSS dans les navigateurs modernes
# SECURE_CONTENT_TYPE_NOSNIFF = True # Empêche le mime-type sniffing
# SECURE_SSL_REDIRECT = True         # Force la redirection de tout le trafic en HTTPS
# SECURE_HSTS_SECONDS = 31536000     # HSTS : force le HTTPS pendant 1 an
# SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# SECURE_HSTS_PRELOAD = True

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}