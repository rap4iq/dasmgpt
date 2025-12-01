Инструкции по развертыванию DasmGPT (Production)Этот документ описывает полный процесс развертывания системы DasmGPT на сервере Ubuntu 22.04.1. 🏗️ Архитектура СистемыПроект состоит из следующих компонентов:База Данных (Docker): PostgreSQL 16 с расширением pgvector.Важно: Используется специальный Docker-образ для поддержки векторного поиска.Брокер задач (Docker): Redis.AI Engine (Systemd): Ollama (запущенная локально).Backend (Systemd):Gunicorn: Веб-сервер Django.Celery: Асинхронный воркер (обработка запросов).Frontend (Nginx): Reverse Proxy для раздачи статики и перенаправления запросов.2. 📋 Пошаговое руководствоШаг 1: 🖥️ Подготовка СервераОбновите систему и установите базовые утилиты:sudo apt update && sudo apt upgrade -y
sudo apt install python3-venv python3-pip nginx git docker.io -y
Шаг 2: 🧠 Установка и Настройка AI (Ollama)Установите Ollama:curl -fsSL [https://ollama.com/install.sh](https://ollama.com/install.sh) | sh
Настройте сервис (для параллелизма):Отредактируйте файл службы: sudo systemctl edit ollama.serviceДобавьте в блок [Service]:[Service]
Environment="OLLAMA_NUM_PARALLEL=4"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_KEEP_ALIVE=24h"
Скачайте модели:# Основная модель (SQL + Аналитика)
ollama pull qwen2.5-coder:32b

# Модель для векторов (Маршрутизатор)
ollama pull nomic-embed-text
Шаг 3: 📦 База Данных и Redis (Docker)Запустите контейнеры. Мы используем порт 5433 для базы, чтобы избежать конфликтов.# 1. Запуск Redis
sudo docker run -d --name dasm-redis -p 6379:6379 --restart always redis:7

# 2. Запуск PostgreSQL с pgvector
sudo docker run -d \
  --name dasm-db-vector \
  -e POSTGRES_DB=dasmdb \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=strong_password \
  -p 5433:5432 \
  --restart always \
  pgvector/pgvector:pg16
Шаг 4: 📂 Развертывание КодаКлонируйте репозиторий:cd /home/ubuntu
git clone [URL_ВАШЕГО_РЕПОЗИТОРИЯ] DasmGPT
cd DasmGPT
Создайте виртуальное окружение:python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
Шаг 5: ⚙️ Конфигурация (.env)Создайте файл .env в корне проекта: nano .env# --- Django ---
SECRET_KEY=сгенерируйте_сложный_ключ
DEBUG=False
ALLOWED_HOSTS=ваш-домен.com,IP-сервера

# --- Database (Подключение к Docker контейнеру) ---
POSTGRES_DB=dasmdb
POSTGRES_USER=postgres
POSTGRES_PASSWORD=strong_password
POSTGRES_HOST=localhost
POSTGRES_PORT=5433

# --- Redis ---
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# --- AI Settings ---
OLLAMA_HOST=http://localhost:11434
OLLAMA_SQL_MODEL=qwen2.5-coder:32b
OLLAMA_SUMMARY_MODEL=qwen2.5-coder:32b

# --- Security (Шифрование паролей в БД) ---
# Сгенерируйте новый ключ командой: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FERNET_KEY=ваш_сгенерированный_ключ
Шаг 6: 🛠️ Инициализация Django# 1. Примените миграции (это создаст таблицы и включит расширение vector)
python manage.py migrate

# 2. Соберите статику
python manage.py collectstatic --no-input

# 3. Создайте суперпользователя (для входа в админку)
python manage.py createsuperuser
Шаг 7: 🚀 Запуск Служб (Systemd)Используйте файлы из папки deployment_configs/.Скопируйте и отредактируйте пути:В файлах gunicorn.service и celery.service убедитесь, что пути указывают на /home/ubuntu/DasmGPT.Активируйте службы:sudo cp deployment_configs/gunicorn.service /etc/systemd/system/
sudo cp deployment_configs/celery.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable gunicorn celery
sudo systemctl start gunicorn celery
Настройте Nginx:sudo cp deployment_configs/nginx.conf /etc/nginx/sites-available/dasmgpt
# (Отредактируйте server_name внутри файла!)

sudo ln -s /etc/nginx/sites-available/dasmgpt /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
HTTPS (SSL):sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d ваш-домен.com
⚡ Шаг 8: ПОСТ-УСТАНОВКА (ОБЯЗАТЕЛЬНО!)После того как сайт заработал, администратор должен выполнить первичную настройку "Мозга", иначе ИИ не будет видеть данные.Зайдите в Админку: https://ваш-домен.com/admin/.Перейдите в раздел AI_CORE -> 1. Источники данных.Создайте подключение к базе данных (в данном случае к localhost, порт 5433, dasmdb).Выберите это подключение и в меню "Actions" нажмите "Запустить интроспекцию".Перейдите в 2. Курируемые Таблицы.Выберите нужные таблицы.В поле "Действие" выберите "🚀 AI: Полная авто-настройка" и нажмите "Выполнить".(Или настройте вручную: поставьте галочки Is enabled и заполните Бизнес-описание).ФИНАЛЬНЫЙ ШАГ: Индексация.Зайдите на сервер в терминал и выполните команду:cd /home/ubuntu/DasmGPT
source venv/bin/activate
python manage.py build_vector_index
Только после Шага 8 система полностью готова к работе.