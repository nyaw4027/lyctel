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
    'cloudinary',
    'cloudinary_storage',
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
    'corsheaders',
    'csp',
    'django.contrib.humanize',
]

# ── Middleware ─────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'csp.middleware.CSPMiddleware',
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
                'staff.context_processors.staff_alerts',
            ],
        },
    },
]

# ── Database ───────────────────────────────────────────────────────────────────
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

# ── Redis ──────────────────────────────────────────────────────────────────────
# Single definition — used by CACHES and CHANNEL_LAYERS below.
REDIS_URL = os.environ.get('REDIS_URL', '')

# ── Cache ──────────────────────────────────────────────────────────────────────
def _build_caches(redis_url):
    if not redis_url:
        return {
            'default': {
                'BACKEND':  'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'lynctel-cache',
            }
        }
    try:
        import redis as _r
        _r.from_url(redis_url, socket_connect_timeout=2).ping()
        return {
            'default': {
                'BACKEND':  'django.core.cache.backends.redis.RedisCache',
                'LOCATION': redis_url,
                'TIMEOUT':  300,
                'OPTIONS':  {
                    'MAX_ENTRIES':            10000,
                    'max_connections':        20,
                    'socket_timeout':         5,
                    'socket_connect_timeout': 3,
                    'retry_on_timeout':       True,
                },
            }
        }
    except Exception:
        # Redis unreachable (billing lapsed, etc.) — fall back silently
        return {
            'default': {
                'BACKEND':  'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'lynctel-cache',
            }
        }

CACHES = _build_caches(REDIS_URL)

# ── Channel layers ─────────────────────────────────────────────────────────────
# socket_keepalive + health_check_interval prevent Railway's idle-connection
# timeout from killing every WebSocket every ~30 seconds.
def _make_redis_host(url):
    import urllib.parse as _p
    try:
        p = _p.urlparse(url)
        cfg = {
            'host': p.hostname or 'localhost',
            'port': p.port or 6379,
            'socket_keepalive':       True,
            'socket_keepalive_options': {},
            'socket_timeout':          30,
            'socket_connect_timeout':  10,
            'retry_on_timeout':        True,
            'health_check_interval':   25,
        }
        if p.password: cfg['password'] = p.password
        db = (p.path or '/0').lstrip('/')
        if db.isdigit(): cfg['db'] = int(db)
        return cfg
    except Exception:
        return url

if REDIS_URL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts':       [_make_redis_host(REDIS_URL)],
                'capacity':     1500,
                'expiry':       60,
                'group_expiry': 900,
            },
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

# ── Media / Storage ────────────────────────────────────────────────────────────
_cloud_name   = config('CLOUDINARY_CLOUD_NAME', default='').strip()
_cloud_key    = config('CLOUDINARY_API_KEY',    default='').strip()
_cloud_secret = config('CLOUDINARY_API_SECRET', default='').strip()
_use_cloudinary = bool(_cloud_name and _cloud_key and _cloud_secret)

if _use_cloudinary:
    import cloudinary, cloudinary.uploader, cloudinary.api
    cloudinary.config(
        cloud_name=_cloud_name, api_key=_cloud_key,
        api_secret=_cloud_secret, secure=True,
    )
    CLOUDINARY_STORAGE = {
        'CLOUD_NAME': _cloud_name,
        'API_KEY':    _cloud_key,
        'API_SECRET': _cloud_secret,
    }
    STORAGES = {
        'default':    {'BACKEND': 'cloudinary_storage.storage.MediaCloudinaryStorage'},
        'staticfiles':{'BACKEND': 'ecommerce.storage.LynctelStaticFilesStorage'},
    }
else:
    STORAGES = {
        'default':    {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles':{'BACKEND': 'ecommerce.storage.LynctelStaticFilesStorage'},
    }

MEDIA_URL  = '/media/'
MEDIA_ROOT = os.environ.get('MEDIA_ROOT', str(BASE_DIR / 'media'))

# ── Auth ───────────────────────────────────────────────────────────────────────
LOGIN_URL           = '/accounts/login/'
LOGIN_REDIRECT_URL  = '/'
LOGOUT_REDIRECT_URL = '/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── Upload limits ──────────────────────────────────────────────────────────────
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# ── CSRF ───────────────────────────────────────────────────────────────────────
CSRF_TRUSTED_ORIGINS = ['https://lynctel.up.railway.app']

# ── Security headers ───────────────────────────────────────────────────────────
# SECURE_SSL_REDIRECT is False — Railway terminates SSL at the load balancer.
# Setting it True causes an infinite redirect loop (Railway already forces HTTPS).
SECURE_PROXY_SSL_HEADER        = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT             = False   # DO NOT change — Railway handles this
SECURE_CONTENT_TYPE_NOSNIFF     = True
SECURE_BROWSER_XSS_FILTER       = True
X_FRAME_OPTIONS                 = 'DENY'
SECURE_REFERRER_POLICY          = 'strict-origin-when-cross-origin'

if not DEBUG:
    SESSION_COOKIE_SECURE        = True
    CSRF_COOKIE_SECURE           = True
    SECURE_HSTS_SECONDS          = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD          = True

# ── Payment gateways ───────────────────────────────────────────────────────────
HUBTEL_CLIENT_ID     = config('HUBTEL_CLIENT_ID',     default='')
HUBTEL_CLIENT_SECRET = config('HUBTEL_CLIENT_SECRET', default='')
HUBTEL_MERCHANT_ACCT = config('HUBTEL_MERCHANT_ACCT', default='')

# Hubtel callback / return URLs
HUBTEL_CALLBACK_URL      = config('HUBTEL_CALLBACK_URL',
                           default='https://lynctel.up.railway.app/checkout/callback/')
HUBTEL_RETURN_URL        = config('HUBTEL_RETURN_URL',
                           default='https://lynctel.up.railway.app/orders/')
HUBTEL_CANCEL_URL        = config('HUBTEL_CANCEL_URL',
                           default='https://lynctel.up.railway.app/checkout/')
HUBTEL_FOOD_CALLBACK_URL = config('HUBTEL_FOOD_CALLBACK_URL',
                           default='https://lynctel.up.railway.app/food/payment/callback/')

# Platform commission (Lynctel keeps this %, rest is owed to vendor)
FOOD_PLATFORM_CUT = config('FOOD_PLATFORM_CUT', default='0.04')  # 4% on food

FLW_PUBLIC_KEY   = config('FLW_PUBLIC_KEY',   default='')
FLW_SECRET_KEY   = config('FLW_SECRET_KEY',   default='')
FLW_WEBHOOK_HASH = config('FLW_WEBHOOK_HASH', default='')

# ── Push notifications helper module ──────────────────────────────────────────
# Local helper: push_notify.py (NOT the django-push-notifications package)
# Import as: from push_notify import send_push_notification

# ── SMS ────────────────────────────────────────────────────────────────────────
ARKESEL_API_KEY   = config('ARKESEL_API_KEY',   default='')
ARKESEL_SENDER_ID = config('ARKESEL_SENDER_ID', default='Lynctel')
ADMIN_PHONE       = config('ADMIN_PHONE',        default='')

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

# ── Rate limiting ──────────────────────────────────────────────────────────────
RATELIMIT_ENABLE    = True
RATELIMIT_USE_CACHE = 'default'

# ── CORS ───────────────────────────────────────────────────────────────────────
CORS_ALLOW_ALL_ORIGINS  = False
CORS_ALLOWED_ORIGINS    = ['https://lynctel.up.railway.app']
CORS_ALLOW_CREDENTIALS  = True

# ── Content Security Policy (django-csp >= 4.0 format) ────────────────────────
CONTENT_SECURITY_POLICY = {
    'DIRECTIVES': {
        'default-src': ("'self'",),
        'script-src':  ("'self'", "'unsafe-inline'", "cdn.jsdelivr.net", "unpkg.com",
                        "cdnjs.cloudflare.com", "maps.googleapis.com"),
        'style-src':   ("'self'", "'unsafe-inline'", "cdn.jsdelivr.net", "unpkg.com",
                        "cdnjs.cloudflare.com", "fonts.googleapis.com"),
        'font-src':    ("'self'", "fonts.gstatic.com"),
        'img-src':     ("'self'", "data:", "blob:",
                        "*.openstreetmap.org",
                        "*.tile.openstreetmap.org",
                        "*.locationiq.com",
                        "res.cloudinary.com",
                        "maps.gstatic.com"),
        'connect-src': ("'self'", "wss:", "ws:",
                        "nominatim.openstreetmap.org",
                        "us1.locationiq.com",
                        "api.locationiq.com",
                        "api.hubtel.com",
                        "sms.arkesel.com"),
        'frame-src':   ("'self'",),
    },
    'REPORT_ONLY': False,
}

# ── Logging ────────────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
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
        'django':         {'handlers': ['console'], 'level': 'ERROR',   'propagate': False},
        'django.request': {'handlers': ['console'], 'level': 'ERROR',   'propagate': False},
        'accounts':       {'handlers': ['console'], 'level': 'INFO',    'propagate': False},
        'payment':        {'handlers': ['console'], 'level': 'INFO',    'propagate': False},
        'notifications':  {'handlers': ['console'], 'level': 'INFO',    'propagate': False},
        'delivery':       {'handlers': ['console'], 'level': 'INFO',    'propagate': False},
        'rider':          {'handlers': ['console'], 'level': 'INFO',    'propagate': False},
        'food':           {'handlers': ['console'], 'level': 'INFO',    'propagate': False},
    },
}

# ── Sentry ─────────────────────────────────────────────────────────────────────
SENTRY_DSN = config('SENTRY_DSN', default='')
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
        environment=config('DJANGO_ENV', default='production'),
    )

# ── Session performance ─────────────────────────────────────────────────────────
# Store sessions in Redis (same as cache) instead of the database.
# This eliminates one DB query per authenticated request.
# Requires CACHES to be configured with Redis (already done above).
# cached_db: reads from Redis (fast), writes to DB (reliable)
# If Redis pool is exhausted, sessions fall back to DB — no crash
SESSION_ENGINE      = 'django.contrib.sessions.backends.db'
SESSION_CACHE_ALIAS = 'default'
SESSION_COOKIE_AGE  = 1209600   # 2 weeks

# ── Template caching ──────────────────────────────────────────────────────────
# Cache compiled templates in memory — avoids re-parsing on every request.
# Already enabled via django.template.loaders.cached.Loader in production.
# (Django auto-enables this when DEBUG=False with APP_DIRS=True.)

# ── Database query optimisation ───────────────────────────────────────────────
# conn_max_age=600 is set above (reuse DB connections for 10 min) ✓
# ATOMIC_REQUESTS: False (default) — better for read-heavy pages