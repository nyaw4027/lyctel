from pathlib import Path
import os

import dj_database_url
from decouple import config
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Security ───────────────────────────────────────────────────────────────────
SECRET_KEY = config('SECRET_KEY')
DEBUG      = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = [
    '127.0.0.1',
    'localhost',
    '.railway.app',
    'lynctel.up.railway.app',
]

# ── Custom user model ──────────────────────────────────────────────────────────
AUTH_USER_MODEL = 'ecommerce.User'

# ── Applications ───────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'daphne',
    'channels',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Storage
    'cloudinary',
    'cloudinary_storage',
    # Project apps
    'ecommerce',
    'products',
    'cart',
    'order.apps.OrderConfig',
    'payment',
    'delivery.apps.DeliveryConfig',
    'rider',
    'frontend',
    'accounts',
    'dashboard',
    'reviews',
    'vendors',
    'staff',
    'food',
    'chat',
    'livestream',
    'fraud',
    'notifications',
]

# ── Middleware ─────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF     = 'ecommerce.urls'
WSGI_APPLICATION = 'ecommerce.wsgi.application'
ASGI_APPLICATION = 'ecommerce.asgi.application'

# ── Templates ──────────────────────────────────────────────────────────────────
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
                'django.template.context_processors.i18n',
                'ecommerce.context_processors.google_maps',
                'ecommerce.context_processors.rbac_context',
            ],
        },
    },
]

# ── Database ───────────────────────────────────────────────────────────────────
# Priority:
#   1. DATABASE_PRIVATE_URL / DATABASE_URL — Railway auto-injects
#   2. SQLite — local dev only
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
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ── Channel layers (WebSocket / live streaming) ────────────────────────────────
REDIS_URL = os.getenv('REDIS_URL')

if REDIS_URL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG':  {'hosts': [REDIS_URL]},
        },
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        },
    }

# ── Password validation ────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ── Internationalisation ───────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'Africa/Accra'
USE_I18N      = True
USE_L10N      = True
USE_TZ        = True

LANGUAGES = [
    ('en', _('English')),
    ('tw', _('Twi')),
    ('ga', _('Ga')),
    ('ha', _('Hausa')),
]

LOCALE_PATHS = [BASE_DIR / 'locale']

# ── Static files ───────────────────────────────────────────────────────────────
STATIC_URL       = '/static/'
STATIC_ROOT      = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# ── Media / Storage (Cloudinary or local filesystem) ──────────────────────────
_cloud_name   = config('CLOUDINARY_CLOUD_NAME', default='').strip()
_cloud_key    = config('CLOUDINARY_API_KEY',    default='').strip()
_cloud_secret = config('CLOUDINARY_API_SECRET', default='').strip()
_use_cloudinary = bool(_cloud_name and _cloud_key and _cloud_secret)

if _use_cloudinary:
    import cloudinary
    import cloudinary.uploader
    import cloudinary.api

    cloudinary.config(
        cloud_name = _cloud_name,
        api_key    = _cloud_key,
        api_secret = _cloud_secret,
        secure     = True,
    )

    CLOUDINARY_STORAGE = {
        'CLOUD_NAME': _cloud_name,
        'API_KEY':    _cloud_key,
        'API_SECRET': _cloud_secret,
    }

    STORAGES = {
        'default': {
            'BACKEND': 'cloudinary_storage.storage.MediaCloudinaryStorage',
        },
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
        },
    }

    MEDIA_URL  = '/media/'
    MEDIA_ROOT = BASE_DIR / 'media'

else:
    # Railway Volume or local filesystem
    STORAGES = {
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
        },
    }

    MEDIA_URL  = '/media/'
    MEDIA_ROOT = os.environ.get('MEDIA_ROOT', os.path.join(BASE_DIR, 'media'))

# ── Auth ───────────────────────────────────────────────────────────────────────
LOGIN_URL           = '/accounts/login/'
LOGIN_REDIRECT_URL  = '/'
LOGOUT_REDIRECT_URL = '/'

# ── Misc ───────────────────────────────────────────────────────────────────────
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── Cache ──────────────────────────────────────────────────────────────────────
CACHES = {
    'default': {
        'BACKEND':  'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'lynctel-cache',
    }
}

# ── Upload limits (mobile photos / videos) ─────────────────────────────────────
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024   # 10 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024   # 10 MB

# ── CSRF ───────────────────────────────────────────────────────────────────────
CSRF_TRUSTED_ORIGINS = ['https://lynctel.up.railway.app']

# ── Security headers (production only) ────────────────────────────────────────
if not DEBUG:
    SECURE_PROXY_SSL_HEADER     = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT         = False   # Railway handles HTTPS termination
    SESSION_COOKIE_SECURE       = True
    CSRF_COOKIE_SECURE          = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS             = 'DENY'

# ── Payment gateways ───────────────────────────────────────────────────────────

# Hubtel — primary payment gateway (replaces Paystack)
# Get from: merchants.hubtel.com → Settings → API
HUBTEL_CLIENT_ID     = config('HUBTEL_CLIENT_ID',     default='')
HUBTEL_CLIENT_SECRET = config('HUBTEL_CLIENT_SECRET', default='')
HUBTEL_MERCHANT_ACCT = config('HUBTEL_MERCHANT_ACCT', default='')

# Flutterwave — secondary gateway (kept as fallback)
# FIXED: was FLW_WEBHOOK_SECRET but payment/views.py reads FLW_WEBHOOK_HASH
FLW_PUBLIC_KEY   = config('FLW_PUBLIC_KEY',   default='')
FLW_SECRET_KEY   = config('FLW_SECRET_KEY',   default='')
FLW_WEBHOOK_HASH = config('FLW_WEBHOOK_HASH', default='')   # was FLW_WEBHOOK_SECRET

# ── SMS — Arkesel ──────────────────────────────────────────────────────────────
ARKESEL_API_KEY   = config('ARKESEL_API_KEY',   default='')
ARKESEL_SENDER_ID = config('ARKESEL_SENDER_ID', default='Lynctel')

# ── Admin alerts (payout failures etc.) ───────────────────────────────────────
# SMS is sent to this number when a vendor MoMo disbursement fails.
ADMIN_PHONE = config('ADMIN_PHONE', default='')

# ── Email ──────────────────────────────────────────────────────────────────────
EMAIL_BACKEND       = config('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST          = config('EMAIL_HOST',    default='smtp.gmail.com')
EMAIL_PORT          = config('EMAIL_PORT',    default=587, cast=int)
EMAIL_USE_TLS       = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER     = config('EMAIL_HOST_USER',     default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL  = config('DEFAULT_FROM_EMAIL',  default='Lynctel <noreply@lynctel.com>')

# ── Maps ───────────────────────────────────────────────────────────────────────
LOCATIONIQ_API_KEY = config('LOCATIONIQ_API_KEY', default='')

# ── Web Push (VAPID) ───────────────────────────────────────────────────────────
VAPID_PUBLIC_KEY  = config('VAPID_PUBLIC_KEY',  default='')
VAPID_PRIVATE_KEY = config('VAPID_PRIVATE_KEY', default='')
VAPID_ADMIN_EMAIL = config('VAPID_ADMIN_EMAIL', default='admin@lynctel.com')

# ── Logging ────────────────────────────────────────────────────────────────────
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
    'root': {
        'handlers': ['console'],
        'level':    'WARNING',
    },
    'loggers': {
        'django':         {'handlers': ['console'], 'level': 'ERROR', 'propagate': False},
        'django.request': {'handlers': ['console'], 'level': 'ERROR', 'propagate': False},
        'accounts':       {'handlers': ['console'], 'level': 'INFO',  'propagate': False},
        'ecommerce':      {'handlers': ['console'], 'level': 'INFO',  'propagate': False},
        # Payment + payout logging — shows in Railway logs so you can see
        # every Hubtel transfer attempt and any payout failures in real time.
        'payment':        {'handlers': ['console'], 'level': 'INFO',  'propagate': False},
        'notifications':  {'handlers': ['console'], 'level': 'INFO',  'propagate': False},
    },
}

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# ── Sentry error tracking ──────────────────────────────────────────────────────
# Set SENTRY_DSN in Railway environment variables.
# Get a free DSN at https://sentry.io (Lynctel → Settings → DSN)
SENTRY_DSN = config('SENTRY_DSN', default='')
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,      # 10% of requests traced for performance
        profiles_sample_rate=0.05,   # 5% profiled
        send_default_pii=False,       # never send PII (GDPR safe)
        environment=config('DJANGO_ENV', default='production'),
    )

# ── Channels / WebSocket channel layer ────────────────────────────────────────
# CRITICAL: without Redis, WebSockets only work on ONE worker process.
# Railway auto-scales — add the Redis add-on and set REDIS_URL.
REDIS_URL = config('REDIS_URL', default='redis://localhost:6379')

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG':  {'hosts': [REDIS_URL]},
    }
}

# ── Production security headers ────────────────────────────────────────────────
# These all default to off to allow local HTTP dev, but must be on in prod.
if not DEBUG:
    SECURE_SSL_REDIRECT          = True
    SECURE_HSTS_SECONDS          = 31536000   # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD          = True
    SESSION_COOKIE_SECURE        = True
    CSRF_COOKIE_SECURE           = True
    SECURE_CONTENT_TYPE_NOSNIFF  = True
    SECURE_BROWSER_XSS_FILTER    = True
    X_FRAME_OPTIONS              = 'DENY'
    SECURE_REFERRER_POLICY       = 'strict-origin-when-cross-origin'

# ── Cache backend (Redis) ──────────────────────────────────────────────────────
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': REDIS_URL,
        'TIMEOUT':  300,   # 5 minutes default
        'OPTIONS':  {'MAX_ENTRIES': 10000},
    }
}

# ── Rate limiting (django-ratelimit) ───────────────────────────────────────────
# pip install django-ratelimit
# Cart/payment endpoints: 20 requests/minute per user
RATELIMIT_ENABLE = True
RATELIMIT_USE_CACHE = 'default'