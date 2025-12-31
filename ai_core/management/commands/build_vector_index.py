from django.core.management.base import BaseCommand
from ai_core.models import SchemaTable, SchemaColumn
import ollama
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Генерирует векторы (embeddings) для описаний таблиц и колонок.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Запуск индексации базы знаний..."))

        # 1. Проверяем подключение к Ollama и ищем правильную модель
        OLLAMA_HOST = getattr(settings, 'OLLAMA_HOST', 'http://localhost:11434')
        client = ollama.Client(host=OLLAMA_HOST)

        target_model_base = 'nomic-embed-text'
        actual_model_name = None

        try:
            # Получаем список доступных моделей
            models_response = client.list()
            # models_response['models'] - это список объектов. У каждого есть поле 'model' или 'name'
            available_models = [m['model'] for m in models_response['models']]

            # Ищем подходящую
            for m in available_models:
                if target_model_base in m:
                    actual_model_name = m
                    break

            if not actual_model_name:
                # Если не нашли в списке, попробуем дефолтную, вдруг список пуст но модель есть
                actual_model_name = 'nomic-embed-text'
                # Попытка проверить
                client.embeddings(model=actual_model_name, prompt="test")

            self.stdout.write(f"Ollama доступна. Используем модель: {actual_model_name}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Ошибка подключения к Ollama: {e}"))
            self.stdout.write(
                "Убедитесь, что Ollama запущена (systemctl start ollama) и модель скачана (ollama pull nomic-embed-text)")
            return

        # ==========================================
        # 2. Индексируем ТАБЛИЦЫ
        # ==========================================
        tables = SchemaTable.objects.filter(is_enabled=True)
        self.stdout.write(f"Найдено {tables.count()} активных таблиц.")

        for table in tables:
            if not table.description_ru:
                self.stdout.write(self.style.WARNING(f"  [SKIP] Таблица {table.table_name}: нет описания"))
                continue

            try:
                response = client.embeddings(model=actual_model_name, prompt=table.description_ru)
                vector = response['embedding']
                table.embedding = vector
                table.save(update_fields=['embedding'])
                self.stdout.write(f"  [OK] Таблица: {table.table_name}")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  [FAIL] Таблица {table.table_name}: {e}"))

        # ==========================================
        # 3. Индексируем КОЛОНКИ
        # ==========================================
        columns = SchemaColumn.objects.filter(is_enabled=True)
        self.stdout.write(f"Найдено {columns.count()} активных колонок.")

        for col in columns:
            if not col.description_ru:
                continue

            try:
                text_to_embed = f"Таблица {col.schema_table.table_name}, колонка {col.column_name}: {col.description_ru}"

                response = client.embeddings(model=actual_model_name, prompt=text_to_embed)
                vector = response['embedding']
                col.embedding = vector
                col.save(update_fields=['embedding'])

                self.stdout.write(".", ending="")
                self.stdout.flush()

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"\n  [FAIL] Колонка {col.column_name}: {e}"))

        self.stdout.write("\n")
        self.stdout.write(self.style.SUCCESS("Индексация успешно завершена!"))