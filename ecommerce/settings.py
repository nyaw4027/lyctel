from pathlib import Path
import os
import json
import dj_database_url
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('323')

# DEBUG only controls error pages / debug toolbar — NOT database or storage choice
DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'lynctel.up.railway.app']
CSRF_TRUSTED_ORIGINS = ['https://lynctel.up.railway.app']

# ── Custom User Model ───────────────────────────────────────
AUTH_USER_MODEL = 'ecommerce.User'

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'ecommerce',
    'products',
    'cart',
    'order',
    'payment',
    'delivery',
    'rider',
    'frontend',
    'accounts',
    'dashboard',
    'reviews',
    'vendors',
    'staff',
    'food',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'ecommerce.middleware.RBACMiddleware',
]

ROOT_URLCONF = 'ecommerce.urls'

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
                'ecommerce.context_processors.rbac_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'ecommerce.wsgi.application'
ASGI_APPLICATION  = 'ecommerce.asgi.application'

# ══════════════════════════════════════════════════════════════
# DATABASE — ALWAYS PostgreSQL on Railway, regardless of DEBUG.
# This is the #1 fix: users were vanishing because DEBUG=True
# silently switched to a throwaway SQLite file that Railway
# wipes on every redeploy.
# ══════════════════════════════════════════════════════════════
_db_url = (
    os.environ.get('DATABASE_PRIVATE_URL')
    or os.environ.get('DATABASE_URL')
)

if _db_url:
    DATABASES = {
        'default': dj_database_url.parse(_db_url, conn_max_age=600)
    }
else:
    # Only used for local development with no DATABASE_URL set
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME':   BASE_DIR / 'db.sqlite3',
        }
    }


# ── Password validation ────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'Africa/Accra'
USE_I18N      = True
USE_TZ        = True

# ══════════════════════════════════════════════════════════════
# STATIC & MEDIA — Firebase is OPTIONAL.
# If FIREBASE_STORAGE_BUCKET + GOOGLE_APPLICATION_CREDENTIALS_JSON
# are BOTH present and valid, use Firebase/GCS.
# Otherwise fall back to local disk + WhiteNoise so the
# site NEVER crashes due to missing Firebase config.
# ══════════════════════════════════════════════════════════════
STATIC_URL       = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT      = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

FIREBASE_STORAGE_BUCKET = os.environ.get('FIREBASE_STORAGE_BUCKET', '')
_firebase_creds_json    = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON', '')

FIREBASE_ENABLED = False

if FIREBASE_STORAGE_BUCKET and _firebase_creds_json:
    try:
        # Validate the JSON is actually valid before relying on it
        json.loads(_firebase_creds_json)

        # Write credentials to a temp file — google-cloud-storage needs a file path
        _creds_path = BASE_DIR / 'firebase-credentials.json'
        if not _creds_path.exists():
            with open(_creds_path, 'w') as f:
                f.write(_firebase_creds_json)

        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(_creds_path)

        STORAGES = {
            'default': {
                'BACKEND': 'ecommerce.firebase_storage_backend.FirebaseMediaStorage',
            },
            'staticfiles': {
                'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
            },
        }
        FIREBASE_ENABLED = True

    except (json.JSONDecodeError, Exception) as e:
        # Firebase creds malformed — DO NOT crash. Fall back to local storage.
        print(f"⚠️  Firebase Storage disabled — invalid credentials: {e}")
        FIREBASE_ENABLED = False

if not FIREBASE_ENABLED:
    # Safe fallback: local filesystem storage for media,
    # WhiteNoise for static files (works great on Railway)
    STORAGES = {
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
    }


# ── Auth redirects ─────────────────────────────────────────
LOGIN_URL           = '/accounts/login/'
LOGIN_REDIRECT_URL  = '/'
LOGOUT_REDIRECT_URL = '/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CACHES = {
    'default': {
        'BACKEND':  'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'lynctel-cache',
    }
}

SESSION_COOKIE_AGE         = 60 * 60 * 24 * 30
SESSION_SAVE_EVERY_REQUEST = True

from django.contrib.messages import constants as messages
MESSAGE_TAGS = {
    messages.DEBUG:   'debug',
    messages.INFO:    'info',
    messages.SUCCESS: 'success',
    messages.WARNING: 'warning',
    messages.ERROR:   'error',
}

# ── Payments ─────────────────────────────────────────────────
FLW_PUBLIC_KEY     = config('FLW_PUBLIC_KEY',     default='')
FLW_SECRET_KEY     = config('FLW_SECRET_KEY',     default='')
FLW_WEBHOOK_SECRET = config('FLW_WEBHOOK_SECRET', default='')
PAYSTACK_PUBLIC_KEY = config('PAYSTACK_PUBLIC_KEY', default='')
PAYSTACK_SECRET_KEY = config('PAYSTACK_SECRET_KEY', default='')

SUPPORT_WHATSAPP = '233558040216'

DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

GOOGLE_MAPS_API_KEY = config('GOOGLE_MAPS_API_KEY', default='')

# ── Security: only enforce HTTPS redirects in production ───
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT     = True
    SESSION_COOKIE_SECURE   = True
    CSRF_COOKIE_SECURE      = True