"""
Base settings for Humatron PDF Processing SaaS (humatron.me).
"""
import os
from pathlib import Path
import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ['humatron.me', 'www.humatron.me', 'localhost', '127.0.0.1']),
    DJANGO_CSRF_TRUSTED_ORIGINS=(list, ['https://humatron.me', 'https://www.humatron.me']),
    MAX_UPLOAD_SIZE_MB=(int, 50),
    MAX_PAGES=(int, 200),
    MAX_PROCESSING_TIME_SECONDS=(int, 180),
    FILE_RETENTION_DAYS=(int, 7),
    TELEBIRR_USD_TO_ETB_RATE=(float, 135.0),
    TELEBIRR_DEFAULT_PRICE_ETB=(float, 6750.0),
    SECURE_SSL_REDIRECT=(bool, False),
    SESSION_COOKIE_SECURE=(bool, False),
    CSRF_COOKIE_SECURE=(bool, False),
)

# Take environment variables from .env file if present
env_file = BASE_DIR / '.env'
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env('DJANGO_SECRET_KEY')
DEBUG = env('DJANGO_DEBUG')
ALLOWED_HOSTS = env('DJANGO_ALLOWED_HOSTS')
CSRF_TRUSTED_ORIGINS = env('DJANGO_CSRF_TRUSTED_ORIGINS')

if DEBUG:
    # Allow local network hosting and testing
    if '*' not in ALLOWED_HOSTS:
        ALLOWED_HOSTS = list(ALLOWED_HOSTS) + ['*']
    
    # Automatically add detected local network IPs to CSRF_TRUSTED_ORIGINS
    import socket
    local_origins = list(CSRF_TRUSTED_ORIGINS)
    detected_ips = ['0.0.0.0', '127.0.0.1', 'localhost']
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        detected_ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    for ip in detected_ips:
        for port in [8000, 8080]:
            origin = f'http://{ip}:{port}'
            if origin not in local_origins:
                local_origins.append(origin)
    CSRF_TRUSTED_ORIGINS = local_origins

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third party
    'rest_framework',
    
    # Humatron Apps
    'accounts.apps.AccountsConfig',
    'subscriptions.apps.SubscriptionsConfig',
    'payments.apps.PaymentsConfig',
    'pdf_processor.apps.PdfProcessorConfig',
    'notifications.apps.NotificationsConfig',
    'contact.apps.ContactConfig',
    'usage.apps.UsageConfig',
    'audit.apps.AuditConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'accounts.middleware.RateLimitMiddleware',
]

ROOT_URLCONF = 'config.urls'

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
                'accounts.context_processors.humatron_globals',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Database
# Default: PostgreSQL connection configured via DATABASE_URL
DATABASES = {
    'default': env.db('DATABASE_URL')
}

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 10},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files (Uploaded and processed PDFs)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

# Redis & Caching
REDIS_URL = env('REDIS_URL', default='redis://127.0.0.1:6379/0')
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': REDIS_URL,
    }
}

# Celery Configuration
CELERY_BROKER_URL = env('CELERY_BROKER_URL', default=REDIS_URL)
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', default=REDIS_URL)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = env('MAX_PROCESSING_TIME_SECONDS', default=180) + 30
CELERY_TASK_ALWAYS_EAGER = env.bool('CELERY_TASK_ALWAYS_EAGER', default=True)
CELERY_TASK_EAGER_PROPAGATES = True


# SMTP Email Configuration (Namecheap Private Email)
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
SMTP_HOST = env('SMTP_HOST', default='mail.privateemail.com')
SMTP_PORT = env.int('SMTP_PORT', default=587)
SMTP_USE_TLS = env.bool('SMTP_USE_TLS', default=True)

EMAIL_HOST = SMTP_HOST
EMAIL_PORT = SMTP_PORT
EMAIL_USE_TLS = SMTP_USE_TLS

# Dedicated Humatron Email Accounts
SUPPORT_EMAIL = env('SUPPORT_EMAIL', default='support@humatron.me')
SUPPORT_EMAIL_APP_PASSWORD = env('SUPPORT_EMAIL_APP_PASSWORD', default='')

CONTACT_EMAIL = env('CONTACT_EMAIL', default='contact@humatron.me')
CONTACT_EMAIL_APP_PASSWORD = env('CONTACT_EMAIL_APP_PASSWORD', default='')

ADMIN_EMAIL = env('ADMIN_EMAIL', default='admin@humatron.me')

# Standard Django SMTP uses the primary transactional support mailbox
EMAIL_HOST_USER = SUPPORT_EMAIL
EMAIL_HOST_PASSWORD = SUPPORT_EMAIL_APP_PASSWORD

DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default=f"Humatron Support <{SUPPORT_EMAIL}>")
DEFAULT_CONTACT_FROM_EMAIL = env('DEFAULT_CONTACT_FROM_EMAIL', default=f"Humatron Contact <{CONTACT_EMAIL}>")

# Site Domain
SITE_DOMAIN = 'humatron.me'

# PDF Processing & Limits
MAX_UPLOAD_SIZE_MB = env.int('MAX_UPLOAD_SIZE_MB', default=50)
MAX_PAGES = env.int('MAX_PAGES', default=200)
MAX_PROCESSING_TIME_SECONDS = env.int('MAX_PROCESSING_TIME_SECONDS', default=180)
FILE_RETENTION_DAYS = env.int('FILE_RETENTION_DAYS', default=7)
PDF_RENDER_DPI = env.int('PDF_RENDER_DPI', default=200)  # 200 DPI for high visual fidelity
PDF_METADATA_PRODUCER = env.str('PDF_METADATA_PRODUCER', default='Humatron PDF Processor')
PDF_METADATA_TITLE = env.str('PDF_METADATA_TITLE', default='')
PDF_METADATA_CREATOR = env.str('PDF_METADATA_CREATOR', default='')

# OCR Stealth PDF Degradation Settings
PDF_STEALTH_ENABLED = env.bool('PDF_STEALTH_ENABLED', default=True)
PDF_STEALTH_SSIM = env.float('PDF_STEALTH_SSIM', default=0.990)  # Tighter SSIM for near-identical visual output
PDF_STEALTH_STRENGTH = env('PDF_STEALTH_STRENGTH', default=None)
if PDF_STEALTH_STRENGTH is not None and str(PDF_STEALTH_STRENGTH).strip():
    try:
        PDF_STEALTH_STRENGTH = float(PDF_STEALTH_STRENGTH)
    except ValueError:
        PDF_STEALTH_STRENGTH = None
else:
    PDF_STEALTH_STRENGTH = None
PDF_STEALTH_GEO = env.float('PDF_STEALTH_GEO', default=0.0)
PDF_STEALTH_TILE = env.int('PDF_STEALTH_TILE', default=256)
PDF_STEALTH_SKIP = env.str('PDF_STEALTH_SKIP', default='overlay,geometry')
PDF_STEALTH_ONLY = env.str('PDF_STEALTH_ONLY', default='')
PDF_STEALTH_SEED = env.int('PDF_STEALTH_SEED', default=0)

# Subtle Noise & Invisible Unicode OCR Settings
PDF_SUBTLE_NOISE_ENABLED = env.bool('PDF_SUBTLE_NOISE_ENABLED', default=True)
PDF_SUBTLE_NOISE_STRENGTH = env.float('PDF_SUBTLE_NOISE_STRENGTH', default=0.15)  # 0.15 = extremely subtle, near-imperceptible
PDF_INVISIBLE_OCR_ENABLED = env.bool('PDF_INVISIBLE_OCR_ENABLED', default=False)
PDF_INVISIBLE_OCR_DPI = env.int('PDF_INVISIBLE_OCR_DPI', default=200)
PDF_MAX_INVISIBLE_BYTES = env.int('PDF_MAX_INVISIBLE_BYTES', default=1024 * 1024)  # 1 MB



# Payments Configuration
TELEBIRR_RECEIVER_PHONE = env('TELEBIRR_RECEIVER_PHONE', default='0911000000')
TELEBIRR_MERCHANT_NAME = env('TELEBIRR_MERCHANT_NAME', default='Humatron')
TELEBIRR_USD_TO_ETB_RATE = env.float('TELEBIRR_USD_TO_ETB_RATE', default=135.0)
TELEBIRR_DEFAULT_PRICE_ETB = env.float('TELEBIRR_DEFAULT_PRICE_ETB', default=6750.0)

# Binance Pay Configuration (Official Merchant API)
BINANCE_PAY_CERTIFICATE_SN = env('BINANCE_PAY_CERTIFICATE_SN', default=env('BINANCE_PAY_API_KEY', default=''))
BINANCE_PAY_API_KEY = env('BINANCE_PAY_API_KEY', default=BINANCE_PAY_CERTIFICATE_SN)
BINANCE_PAY_SECRET_KEY = env('BINANCE_PAY_SECRET_KEY', default='')
BINANCE_PAY_BASE_URL = env('BINANCE_PAY_BASE_URL', default='https://bpay.binanceapi.com')
BINANCE_PAY_RETURN_URL = env('BINANCE_PAY_RETURN_URL', default='')
BINANCE_PAY_CANCEL_URL = env('BINANCE_PAY_CANCEL_URL', default='')
BINANCE_PAY_WEBHOOK_URL = env('BINANCE_PAY_WEBHOOK_URL', default='')

# Security & Cookies
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True

SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=False)
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=False)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=False)

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'accounts:dashboard'
LOGOUT_REDIRECT_URL = 'accounts:login'

# Structured Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} [{name}:{lineno}] {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'humatron': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
