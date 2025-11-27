import os
from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []



INSTALLED_APPS = [
    'chat',
    'users',
    'ai_core',
    'encrypted_fields',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
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

ROOT_URLCONF = 'dasm.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'dasm.wsgi.application'

AUTH_USER_MODEL = 'users.User'
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'users.backends.EmailBackend',
]
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('POSTGRES_DB'),
        'USER': config('POSTGRES_USER'),
        'PASSWORD': config('POSTGRES_PASSWORD'),
        'HOST': config('POSTGRES_HOST', 'db'),
        'PORT': config('POSTGRES_PORT', '5432'),
        'AUTOMATIC_REQUEST': True,
    }
}

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://localhost:6379/2",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "COMPRESSOR": "django_redis.compressors.zlib.ZlibCompressor",
        }
    }
}
CACHE_TTL = 60 * 60 * 24



LOGGING_DIR = BASE_DIR / 'logs'
if not os.path.exists(LOGGING_DIR):
    os.makedirs(LOGGING_DIR)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,

    # 2. Форматтеры (Как выглядит строка лога)
    'formatters': {
        'verbose': {
            # Пример: [2023-10-25 14:30:05] [INFO] [chat.tasks:125] [Task-ID: xxx] Сообщение...
            'format': '[{asctime}] [{levelname}] [{name}:{lineno}] {message}',
            'style': '{',
        },
        'simple': {
            'format': '[{levelname}] {message}',
            'style': '{',
        },
    },

    # 3. Хендлеры (Куда писать логи)
    'handlers': {
        # Консоль (для разработки) - показывает всё
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },

        # Файл: errors.log (Только ошибки и критические сбои)
        'file_errors': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'errors.log',
            'maxBytes': 1024 * 1024 * 5,  # 5 MB
            'backupCount': 5,  # Хранить 5 последних файлов
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },

        # Файл: audit.log (Все действия: кто зашел, что спросил, какой SQL)
        'file_audit': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'audit.log',
            'maxBytes': 1024 * 1024 * 10,  # 10 MB
            'backupCount': 10,  # Хранить 10 последних файлов
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
    },

    # 4. Логгеры (Кто пишет)
    'loggers': {
        # Главный логгер Django (ловит всё системное)
        'django': {
            'handlers': ['console', 'file_errors'],
            'level': 'INFO',
            'propagate': True,
        },
        # Наш проект (chat, ai_core, users)
        'chat': {
            'handlers': ['console', 'file_audit', 'file_errors'],
            'level': 'INFO',
            'propagate': False,
        },
        'ai_core': {
            'handlers': ['console', 'file_audit', 'file_errors'],
            'level': 'INFO',
            'propagate': False,
        },
        'users': {
            'handlers': ['console', 'file_audit', 'file_errors'],
            'level': 'INFO',
            'propagate': False,
        },
        # Celery (Важно для отладки воркера)
        'celery': {
            'handlers': ['console', 'file_errors', 'file_audit'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
# Password validation
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

FERNET_KEYS = [
    config('FERNET_KEY')
]

SALT_KEY = config('SALT_KEY')


LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/users/login/'
LOGIN_REDIRECT_URL = '/admin-panel/dashboard/'
LOGOUT_REDIRECT_URL = '/users/login/'

# Redis broker + result backend
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/1'

# Настройки worker
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300  # сек

OLLAMA_HOST = 'http://localhost:11434'
OLLAMA_MODEL = 'qwen3-coder:30b'
OLLAMA_SQL_TEMPERATURE = 0.0  # 0.0 для точного SQL
OLLAMA_TEMPERATURE = 1.0 # 0.7 для "креативного" текста
OLLAMA_SQL_MODEL = 'qwen3-coder:30b'

QUERY_ROW_LIMIT = 1000
QUERY_TIMEOUT_MS = 30000

DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000
