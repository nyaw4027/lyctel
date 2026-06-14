from pathlib import Path
import os
import dj_database_url
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Security ───────────────────────────────────────────────
SECRET_KEY = config('SECRET_KEY')
DEBUG      = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = [
    '127.0.0.1',
    'localhost',
    'lynctel.up.railway.app',
]

# ── Custom User Model ──────────────────────────────────────
AUTH_USER_MODEL = 'ecommerce.User'

# ── Apps ───────────────────────────────────────────────────
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

# ── Middleware ─────────────────────────────────────────────
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'ecommerce.urls'

# ── Templates ──────────────────────────────────────────────
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

WSGI_APPLICATION = 'ecommerce.wsgi.application'

# ══════════════════════════════════════════════════════════════
# DATABASE
# Priority order:
#   1. DATABASE_PRIVATE_URL or DATABASE_URL  (Railway auto-injects these)
#   2. Individual vars: NAME, USER, PASSWORD, HOST, DBPORT
#      NOTE: We read DBPORT (not PORT) to avoid colliding with Railway's
#      web-server PORT variable. Rename PORT→DBPORT in Railway Variables.
#   3. SQLite (local dev only — never used on Railway)
# ══════════════════════════════════════════════════════════════
_db_url = (
    os.environ.get('DATABASE_PRIVATE_URL') or
    os.environ.get('DATABASE_URL')
)

if _db_url:
    DATABASES = {
        'default': dj_database_url.parse(
            _db_url,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
elif os.environ.get('HOST') or os.environ.get('DB_HOST'):
    DATABASES = {
        'default': {
            'ENGINE':       'django.db.backends.postgresql',
            'NAME':         os.environ.get('NAME',     os.environ.get('DB_NAME',     'railway')),
            'USER':         os.environ.get('USER',     os.environ.get('DB_USER',     'postgres')),
            'PASSWORD':     os.environ.get('PASSWORD', os.environ.get('DB_PASSWORD', '')),
            'HOST':         os.environ.get('HOST',     os.environ.get('DB_HOST',     '')),
            # ↓ DBPORT avoids clash with Railway's web-server PORT variable
            'PORT':         os.environ.get('DBPORT',   os.environ.get('DB_PORT',     '5432')),
            'CONN_MAX_AGE': 600,
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ── Password validation ────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ── Internationalisation ───────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'Africa/Accra'
USE_I18N      = True
USE_TZ        = True

# ── Static files ───────────────────────────────────────────
STATIC_URL       = '/static/'
STATIC_ROOT      = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# ── Media files ────────────────────────────────────────────
MEDIA_URL  = '/media/'
MEDIA_ROOT = os.environ.get('MEDIA_ROOT', os.path.join(BASE_DIR, 'media'))

# ── Storage backends ───────────────────────────────────────
_gac_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON', '')
_bucket   = os.environ.get('FIREBASE_STORAGE_BUCKET', '')

_use_firebase = bool(_gac_json and _bucket and not DEBUG)

if _use_firebase:
    import json, tempfile

    json.loads(_gac_json)

    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.json', delete=False
    )
    tmp.write(_gac_json)
    tmp.close()

    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = tmp.name

    # IMPORTANT: ONLY THIS NAME IS USED BY django-storages
    GS_BUCKET_NAME = _bucket

    STORAGES = {
        "default": {
            "BACKEND": "ecommerce.firebase_storage_backend.FirebaseStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

    MEDIA_URL = f"https://storage.googleapis.com/{_bucket}/media/"

else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }

    MEDIA_URL = "/media/"

# ── Auth redirects ─────────────────────────────────────────
LOGIN_URL           = '/accounts/login/'
LOGIN_REDIRECT_URL  = '/'
LOGOUT_REDIRECT_URL = '/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
ASGI_APPLICATION   = 'ecommerce.asgi.application'

# ── Cache ──────────────────────────────────────────────────
CACHES = {
    'default': {
        'BACKEND':  'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'lynctel-cache',
    }
}

# ── Payment gateways ───────────────────────────────────────
FLW_PUBLIC_KEY      = config('FLW_PUBLIC_KEY',      default='')
FLW_SECRET_KEY      = config('FLW_SECRET_KEY',      default='')
FLW_WEBHOOK_SECRET  = config('FLW_WEBHOOK_SECRET',  default='')
PAYSTACK_PUBLIC_KEY = config('PAYSTACK_PUBLIC_KEY', default='')
PAYSTACK_SECRET_KEY = config('PAYSTACK_SECRET_KEY', default='')

GOOGLE_MAPS_API_KEY = config('GOOGLE_MAPS_API_KEY', default='')

CSRF_TRUSTED_ORIGINS = ['https://lynctel.up.railway.app']

# ── Security headers (production only) ────────────────────
if not DEBUG:
    SECURE_PROXY_SSL_HEADER     = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT         = False
    SESSION_COOKIE_SECURE       = True
    CSRF_COOKIE_SECURE          = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS             = 'DENY'

# ── Logging ────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {message}',
            'style':  '{',
        },
    },
    'handlers': {
        'console': {
            'class':     'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {'handlers': ['console'], 'level': 'WARNING'},
    'loggers': {
        'django':         {'handlers': ['console'], 'level': 'ERROR', 'propagate': False},
        'django.request': {'handlers': ['console'], 'level': 'ERROR', 'propagate': False},
        'accounts':       {'handlers': ['console'], 'level': 'INFO',  'propagate': False},
        'ecommerce':      {'handlers': ['console'], 'level': 'INFO',  'propagate': False},
    },
}