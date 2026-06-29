import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-change-this-before-deploy')
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'jtp.apps.JtpConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'jtp.user_auth.UserAccessLogMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'jtp' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'jtp.context_processors.jtp_user_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ── Database ──────────────────────────────────────────────────────────────────
SCHEMA_NAME = os.getenv('SCHEMA_NAME', 'VNAT_TEGAF_JTP')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'HOST': os.getenv('DB_HOST', '10-108-201-248.dbaas.intel.com'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'NAME': os.getenv('DB_NAME', 'vnat_teg_af_database'),
        'USER': os.getenv('DB_USER', 'i456en9l4kalgwq0qarl_admin'),
        'PASSWORD': os.getenv('DB_PASS', ''),
        'OPTIONS': {
            'sslmode': os.getenv('DB_SSLMODE', 'require'),
            # Use quoted schema name because VNAT_TEGAF_JTP is mixed-case
            'options': f'-c search_path="{SCHEMA_NAME}",public',
        },
    }
}

# ── Sessions ──────────────────────────────────────────────────────────────────
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = 86400        # 1 day
SESSION_SAVE_EVERY_REQUEST = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# ── Static files ──────────────────────────────────────────────────────────────
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'jtp' / 'static']

# ── i18n ──────────────────────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── inf_data table configuration ──────────────────────────────────────────────
# Adjust these environment variables if your inf_data table uses different column names
INF_DATA_TABLE = os.getenv('INF_DATA_TABLE', f'"{SCHEMA_NAME}"."inf_data"')
INF_DATA_COL_WWID = os.getenv('INF_DATA_COL_WWID', 'wwid')
INF_DATA_COL_COURSE_ID = os.getenv('INF_DATA_COL_COURSE_ID', 'Number_ID')
INF_DATA_COL_STATUS = os.getenv('INF_DATA_COL_STATUS', 'Status')
INF_DATA_COL_COMPLETION_DATE = os.getenv('INF_DATA_COL_COMPLETION_DATE', 'course_completion')

# ── JTP Admin users (hard-coded; also stored in jtp_admin_users table) ────────
JTP_ADMIN_ISIDS = ['hoangp5', 'ngocanhm']
JTP_ADMIN_EMAILS = [
    'hoang.phuc.thinh.nguyen@intel.com',
    'ngoc.anh.minh.huynh@intel.com',
]

# ── Logging ───────────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
