"""
Django settings for JAR (Játékvezetői Adminisztrációs Rendszer) project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-change-me-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Local apps
    'accounts',
    'referees',
    'matches',
    'billing',
    'education',
    'documents',
    'audit',
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

ROOT_URLCONF = 'jar.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'accounts.context_processors.unread_notifications',
                'accounts.context_processors.global_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'jar.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'jar_db'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}

# Use SQLite for development if DB_ENGINE is sqlite
if os.getenv('DB_ENGINE', '').lower() == 'sqlite':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Custom user model
AUTH_USER_MODEL = 'accounts.User'


# Internationalization

LANGUAGE_CODE = 'hu'

TIME_ZONE = 'Europe/Budapest'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

# Media files (uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# Default primary key field type

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Email settings
# SendPulse SMTP configuration:
#   EMAIL_HOST=smtp-pulse.com
#   EMAIL_PORT=587
#   EMAIL_HOST_USER=your-sendpulse-username
#   EMAIL_HOST_PASSWORD=your-sendpulse-password
#   EMAIL_USE_TLS=True
#   DEFAULT_FROM_EMAIL=JAR <noreply@yourdomain.com>
#   TEST_EMAIL=True  # Set to True to send real emails even in DEBUG mode

# Use SMTP if not DEBUG, or if TEST_EMAIL is explicitly enabled
TEST_EMAIL = os.getenv('TEST_EMAIL', 'False').lower() in ('true', '1', 'yes')
if DEBUG and not TEST_EMAIL:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp-pulse.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 'yes')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'Magyar Floorball Szakszövetség | Játékvezetői Testület <noreply@example.com>')
SITE_URL = os.getenv('SITE_URL', 'http://localhost:8000' if DEBUG else 'https://jar.hu')


# Cloudflare Turnstile settings

TURNSTILE_SITE_KEY = os.getenv('TURNSTILE_SITE_KEY', '')
TURNSTILE_SECRET_KEY = os.getenv('TURNSTILE_SECRET_KEY', '')


# Session settings

SESSION_COOKIE_AGE = 28800  # 8 óra
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG


# Login settings

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'accounts:dashboard'
LOGOUT_REDIRECT_URL = 'accounts:login'


# Admin settings
# In production, set ADMIN_ENABLED=False to completely disable /admin access
ADMIN_ENABLED = os.getenv('ADMIN_ENABLED', 'True').lower() in ('true', '1', 'yes')
# Secret path for admin (only used if someone knows the URL - but we use internal redirect)
ADMIN_URL_PATH = os.getenv('ADMIN_URL_PATH', 'db-admin-internal/')

# Test server indicator
# Set TEST_SERVER=True in .env to display "TESZT" badge in header
TEST_SERVER = os.getenv('TEST_SERVER', 'False').lower() in ('true', '1', 'yes')
