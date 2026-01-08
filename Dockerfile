FROM python:3.12-slim

# Устанавливаем системные зависимости
# (gcc и libpq-dev нужны для сборки psycopg2, curl для healthcheck)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Создаем рабочую папку внутри контейнера
WORKDIR /app

# Копируем файл зависимостей и устанавливаем их
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код проекта внутрь
COPY . /app/

# Создаем папку для статики
RUN mkdir -p /app/staticfiles

# Открываем порт 8000
EXPOSE 8000

# (Опционально) Скрипт-энтрипоинт, который может выполнять миграции перед стартом
# Но пока оставим простую команду по умолчанию, которую переопределим в compose
CMD ["gunicorn", "dasm.wsgi:application", "--bind", "0.0.0.0:8000"]