🚀 Инструкции по развертыванию DasmGPT (Серверная)

Этот документ описывает шаги, необходимые для развертывания проекта DasmGPT на "боевом" сервере (Ubuntu 22.04).

1. 🏗️ Компоненты Системы

Проект состоит из 4-х основных сервисов, которые должны быть запущены на сервере:

🧠 Ollama: "ИИ-мозг" (как systemd сервис).

🐘 PostgreSQL: База данных (рекомендуется "управляемая" (Managed) или установленная локально).

🎟️ Redis: "Брокер" задач (рекомендуется redis-server или Docker).

🌐 DasmGPT (Django Стек): Само приложение, которое состоит из:

Gunicorn: Веб-сервер (заменяет manage.py runserver).

Celery: Воркер (обработчик ИИ-задач).

Nginx: Reverse Proxy (ваш "вход" с домена).

2. 📋 Пошаговое руководство

Шаг 1: 🖥️ Настройка Сервера (Зависимости)

Перед развертыванием кода убедитесь, что на сервере (Ubuntu 22.04) установлены:

python3-venv, python3-pip

git

nginx

redis-server (или Docker)

sudo apt update && sudo apt upgrade
sudo apt install python3-venv python3-pip nginx redis-server git


Шаг 2: 🧠 Установка Ollama

Ollama должна быть установлена как сервис systemd.

# 1. Установить Ollama
curl -fsSL [https://ollama.com/install.sh](https://ollama.com/install.sh) | sh

# 2. Включить автозапуск
sudo systemctl enable ollama
sudo systemctl start ollama

# 3. Скачать ИИ-модель (указанную в .env или settings.py)
# (Убедитесь, что OLLAMA_MODEL в .env соответствует этой модели)
ollama pull deepseek-r1:8b 


Шаг 3: 📦 Развертывание Кода

Клонируйте проект (например, в /home/ubuntu/DasmGPT):

git clone [URL-репозитория] /home/ubuntu/DasmGPT
cd /home/ubuntu/DasmGPT


Создайте и активируйте виртуальное окружение:

python3 -m venv venv
source venv/bin/activate


Установите Python-зависимости (использует requirements.txt из корня проекта):

pip install -r requirements.txt


Шаг 4: ⚙️ Конфигурация Django

Создайте .env файл в корне проекта (/home/ubuntu/DasmGPT/.env).

Скопируйте в него ВСЕ секретные ключи. (Критически важно!)

# /home/ubuntu/DasmGPT/.env

SECRET_KEY=ВАШ_СЕКРЕТНЫЙ_КЛЮЧ_DJANGO

# Настройки "Продакшен"
DEBUG=False
ALLOWED_HOSTS=ваш-домен.com,IP-сервера
CSRF_TRUSTED_ORIGINS=[https://ваш-домен.com](https://ваш-домен.com)

# Настройки Базы Данных (PostgreSQL)
POSTGRES_DB=имя_вашей_бд
POSTGRES_USER=пользователь_бд
POSTGRES_PASSWORD=пароль_бд
POSTGRES_HOST=localhost (или IP-управляемой-БД)
POSTGRES_PORT=5432

# Настройки Redis (если он на том же хосте)
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# Настройки ИИ (Ollama)
OLLAMA_MODEL=deepseek-r1:8b
OLLAMA_HOST=http://localhost:11434


Примените миграции и соберите статику:
(Убедитесь, что venv активирована)

python manage.py makemigrations
python manage.py migrate
python manage.py collectstatic --no-input


Шаг 5: 🚀 Настройка "Автопилота" (Gunicorn & Celery)

(Файлы gunicorn.service и celery.service должны быть в папке deployment_configs/ этого репозитория).

Скопируйте .service файлы в systemd:

sudo cp deployment_configs/gunicorn.service /etc/systemd/system/gunicorn.service
sudo cp deployment_configs/celery.service /etc/systemd/system/celery.service


(Важно) Если вы клонировали проект НЕ в /home/ubuntu/DasmGPT, отредактируйте пути WorkingDirectory и ExecStart в этих .service файлах.

Запустите и включите автозагрузку:

sudo systemctl daemon-reload
sudo systemctl start gunicorn celery
sudo systemctl enable gunicorn celery


Проверка статуса (необязательно):

sudo systemctl status gunicorn
sudo systemctl status celery


Шаг 6: 🔌 Настройка Nginx

(Файл nginx.conf должен быть в папке deployment_configs/).

Скопируйте конфиг:

sudo cp deployment_configs/nginx.conf /etc/nginx/sites-available/dasmgpt


(Важно) Отредактируйте server_name в /etc/nginx/sites-available/dasmgpt, указав ваш реальный домен.

Активируйте сайт и перезапустите Nginx:

sudo ln -s /etc/nginx/sites-available/dasmgpt /etc/nginx/sites-enabled/

# (Рекомендуется удалить 'default' конфиг Nginx, если он мешает)
# sudo rm /etc/nginx/sites-enabled/default

sudo nginx -t  # (Проверка синтаксиса)
sudo systemctl restart nginx


Шаг 7: 🔒 HTTPS (SSL-Сертификат)

Установите Certbot:

sudo apt install certbot python3-certbot-nginx


Запустите и следуйте инструкциям (укажите ваш домен):

sudo certbot --nginx


✅ Готово!

После Шага 7 ваш проект должен быть "вживую" доступен по адресу https://ваш-домен.com.