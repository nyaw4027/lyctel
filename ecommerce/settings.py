from pathlib import Path
import os
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY')

DEBUG = config('DEBUG', default=False, cast=bool)


ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'lynctel.up.railway.app']

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

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',   # ← serves static in prod
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

# ── Database ───────────────────────────────────────────────
if DEBUG:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('NAME'),
            'USER': config('USER'),
            'PASSWORD': config('PASSWORD'),
            'HOST': config('HOST'),
            'PORT': config('PORT'),
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
STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# ── Media files ────────────────────────────────────────────
MEDIA_URL  = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# ── Firebase / Google Cloud Storage ───────────────────────
# Firebase Storage IS Google Cloud Storage.
# The bucket name is shown in Firebase Console → Storage → gs://lynctel-dd634.appspot.com
# (or gs://lynctel-dd634.firebasestorage.app for newer projects)
#
# Set these environment variables on Railway:
#   FIREBASE_STORAGE_BUCKET   → lynctel-dd634.appspot.com
#   GS_CREDENTIALS            → path to your service-account JSON  (see SETUP.md)

if not DEBUG:
    # ── Firebase Storage bucket name ──────────────────────
    FIREBASE_STORAGE_BUCKET = config('FIREBASE_STORAGE_BUCKET',
                                     default='lynctel-dd634.appspot.com')

    # ── Google Cloud credentials ───────────────────────────
    # Option A (Railway): paste the full JSON into a Railway env var called
    #   GOOGLE_APPLICATION_CREDENTIALS_JSON
    # Option B: mount a .json file and point GS_CREDENTIALS at it.
    import json, tempfile

    _gac_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')
    if _gac_json:
        # Write the JSON string to a temp file so the GCS library can read it
        _tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, prefix='gcp_creds_'
        )
        _tmp.write(_gac_json)
        _tmp.close()
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = _tmp.name

    # ── django-storages Google Cloud backend ───────────────
    GS_BUCKET_NAME       = FIREBASE_STORAGE_BUCKET
    GS_DEFAULT_ACL       = 'publicRead'
    GS_FILE_OVERWRITE    = False
    GS_QUERYSTRING_AUTH  = False

    # Public URL base for media files served from Firebase Storage
    # Firebase Storage public URL pattern:
    #   https://storage.googleapis.com/<bucket>/media/<filename>
    GS_CUSTOM_ENDPOINT = (
        f'https://storage.googleapis.com/{FIREBASE_STORAGE_BUCKET}'
    )

    STORAGES = {
        'staticfiles': {
            # Use WhiteNoise for static — it's simpler and free.
            # Switch to 'ecommerce.firebase_storage_backend.FirebaseStaticStorage'
            # if you want static on Firebase too.
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
        'default': {
            # Media (uploaded images) → Firebase Storage
            'BACKEND': 'ecommerce.firebase_storage_backend.FirebaseMediaStorage',
        },
    }

    STATIC_URL = '/static/'   # WhiteNoise serves from Railway directly
    MEDIA_URL  = f'https://storage.googleapis.com/{FIREBASE_STORAGE_BUCKET}/media/'

    GS_OBJECT_PARAMETERS = {
        'cache_control': 'public, max-age=86400',
    }

# ── Auth redirects ─────────────────────────────────────────
LOGIN_URL           = '/accounts/login/'
LOGIN_REDIRECT_URL  = '/'
LOGOUT_REDIRECT_URL = '/'

# ── Default primary key ────────────────────────────────────
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

ASGI_APPLICATION = "ecommerce.asgi.application"

# ── Cache ──────────────────────────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-eta-cache",
    }
}

# ── Flutterwave (Payment) ──────────────────────────────────
FLW_PUBLIC_KEY     = config('FLW_PUBLIC_KEY',  default='FLWPUBK_TEST-xxxxx')
FLW_SECRET_KEY     = config('FLW_SECRET_KEY',  default='FLWSECK_TEST-xxxxx')
FLW_WEBHOOK_SECRET = config('FLW_WEBHOOK_SECRET', default='my-secret-string')

# ── Google Maps ────────────────────────────────────────────
GOOGLE_MAPS_API_KEY = config('GOOGLE_MAPS_API_KEY', default='')

CSRF_TRUSTED_ORIGINS = [
    'https://lynctel.up.railway.app',
]