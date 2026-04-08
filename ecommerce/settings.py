from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-1mdy3c-obbs2t6g*d43@p%idj3nsgzwf+@9bztmz0zy0m&%e)s'

DEBUG = True

ALLOWED_HOSTS = []

# ── Custom User Model ──────────────────────────────────────
# This tells Django to use YOUR User model instead of the default one
AUTH_USER_MODEL = 'ecommerce.User'

# ── Apps ───────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Your apps
    'ecommerce',   # ← MUST be first — holds the custom User model
    'products',
    'cart',
    'order',
    'payment',
    'delivery',
    'rider',
    'frontend',
    'accounts',
    'dashboard',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
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
        'DIRS': [BASE_DIR / 'templates'],   # ← looks in your /templates folder
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
TIME_ZONE     = 'Africa/Accra'   # ← correct timezone for Ghana 🇬🇭
USE_I18N      = True
USE_TZ        = True

# ── Static files ───────────────────────────────────────────
STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# ── Media files (product images, etc.) ────────────────────
MEDIA_URL  = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# ── Auth redirects ─────────────────────────────────────────
LOGIN_URL          = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# ── Default primary key ────────────────────────────────────
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


FLW_PUBLIC_KEY     = 'FLWPUBK_TEST-xxxxx'   # from Flutterwave dashboard
FLW_SECRET_KEY     = 'FLWSECK_TEST-xxxxx'   # from Flutterwave dashboard
FLW_WEBHOOK_SECRET = 'my-secret-string'     # you choose this
