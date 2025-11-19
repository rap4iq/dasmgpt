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
OLLAMA_MODEL = 'deepseek-r1:8b'
OLLAMA_SQL_TEMPERATURE = 0.0  # 0.0 для точного SQL
OLLAMA_SUMMARY_TEMPERATURE = 0.7 # 0.7 для "креативного" текста


# Максимальное кол-во строк, которое вернет SQL
QUERY_ROW_LIMIT = 1000
# Максимальное время выполнения SQL-запроса (в миллисекундах)
QUERY_TIMEOUT_MS = 30000  # 30 секунд

DDL_TV = """
CREATE TABLE tv (
    id SERIAL PRIMARY KEY,
    channel_name VARCHAR(100),   -- Название ТВ канала
    broadcast_date DATE,         -- Дата эфира
    budget DECIMAL(10, 2),       -- Потраченный бюджет
    coverage INT,                -- Охват
    grp DECIMAL(5, 2)            -- Gross Rating Point
);
"""

DDL_RD = """
CREATE TABLE rd (
    id SERIAL PRIMARY KEY,
    station_name VARCHAR(100),   -- Название радиостанции
    budget DECIMAL(10, 2),       -- Бюджет
    broadcast_period VARCHAR(50),-- Период
    region VARCHAR(100)          -- Регион
);
"""

DDL_OOH = """
CREATE TABLE ooh (
    id SERIAL PRIMARY KEY,
    media_type VARCHAR(100),     -- Тип носителя (билборд, ситилайт)
    city VARCHAR(100),           -- Город
    start_date DATE,             -- Дата начала
    end_date DATE,               -- Дата окончания
    expenses DECIMAL(10, 2)      -- Расходы (синоним budget)
);
"""

# Собираем полную схему для промпта
FULL_DB_SCHEMA = f"""
Инструкции:
- 'expenses' в 'ooh' - это то же самое, что 'budget'.
- 'grp' - это 'Gross Rating Point'.
- 'ooh' - наружная реклама, 'rd' - радио, 'tv' - телевидение.

СХЕМА:
{DDL_TV}

{DDL_RD}

{DDL_OOH}
"""
SQL_ALLOWED_TABLES = ['tv', 'rd', 'ooh']