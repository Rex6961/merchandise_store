"""
Настройки Django для проекта merchandise_store.

Сгенерировано 'django-admin startproject' с использованием Django 5.2.1.

Для получения дополнительной информации об этом файле см.
https://docs.djangoproject.com/en/5.2/topics/settings/

Полный список настроек и их значений см.
https://docs.djangoproject.com/en/5.2/ref/settings/
"""

from pathlib import Path
import logging

from admin_panel.config import settings as app_config

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

logger = logging.getLogger(__name__)

SECRET_KEY = app_config.django.key.get_secret_value() if hasattr(app_config.django.key, 'get_secret_value') else app_config.django.key

PG_DB = app_config.postgres.db.get_secret_value() if hasattr(app_config.postgres.db, 'get_secret_value') else app_config.postgres.db
PG_USER = app_config.postgres.user.get_secret_value() if hasattr(app_config.postgres.user, 'get_secret_value') else app_config.postgres.user
PG_PASSWORD = app_config.postgres.password.get_secret_value() if hasattr(app_config.postgres.password, 'get_secret_value') else app_config.postgres.password
PG_HOST = app_config.postgres.host
PG_PORT = app_config.postgres.port

DEBUG = app_config.django.debug

ALLOWED_HOSTS = []

INSTALLED_APPS = [
    'admin_panel.clients.apps.ClientsConfig',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'import_export',
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

ROOT_URLCONF = 'src.admin_panel.merchandise_store.urls'

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

WSGI_APPLICATION = 'src.admin_panel.merchandise_store.wsgi.application'

ASGI_APPLICATION = 'src.admin_panel.merchandise_store.asgi.application'

# База данных
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql', # Используется PostgreSQL
        'NAME': PG_DB,                             # Имя базы данных
        'USER': PG_USER,                             # Имя пользователя БД
        'PASSWORD': PG_PASSWORD,                     # Пароль пользователя БД
        'HOST': PG_HOST,                             # Хост, на котором работает БД
        'PORT': PG_PORT,                             # Порт для подключения к БД
    }
}


# Валидаторы паролей
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

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


# Интернационализация
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'ru-ru'

TIME_ZONE = 'Europe/Moscow'

USE_I18N = True

USE_TZ = True


# Статические файлы (CSS, JavaScript, Изображения для админки и приложений)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'

STATIC_ROOT = BASE_DIR / 'staticfiles_collected'


MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'mediafiles'


# Тип поля первичного ключа по умолчанию
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

IMPORT_EXPORT_ESCAPE_FORMULAE_ON_EXPORT = True


CELERY_BROKER_URL = 'redis://redis:6379/0'
CELERY_RESULT_BACKEND = 'redis://redis:6379/1'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module}:{lineno} [{process:d}:{thread:d}] {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} {module}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG' if DEBUG else 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file_django': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'django_app.log',
            'maxBytes': 1024 * 1024 * 10,
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file_django'],
            'level': 'INFO',
            'propagate': True,
        },
        'django.request': {
            'handlers': ['console', 'file_django'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['console', 'file_django'],
            'import_export': {
                'handlers': ['console', 'file_django'],
                'level': 'DEBUG' if DEBUG else 'INFO',
            }
        },
        'src.admin_panel.clients': {
            'handlers': ['console', 'file_django'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'src.bot': {
            'handlers': ['console', 'file_django'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'celery': {
            'handlers': ['console', 'file_django'],
            'level': 'INFO',
            'propagate': True,
        },
        'src.admin_panel.merchandise_store.celery': {
             'handlers': ['console', 'file_django'],
             'level': 'INFO',
             'propagate': False,
        }
    },
    'root': {
        'handlers': ['console', 'file_django'],
        'level': 'INFO',
    }
}

LOGS_DIR = BASE_DIR / 'logs'
if not LOGS_DIR.exists():
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"Директория для логов создана: {LOGS_DIR}")
    except Exception as e:
        print(f"Ошибка при создании директории для логов {LOGS_DIR}: {e}")
