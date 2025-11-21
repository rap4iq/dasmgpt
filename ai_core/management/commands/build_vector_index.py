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

        # 1. Проверяем подключение к Ollama
        EMBEDDING_MODEL = 'nomic-embed-text'
        OLLAMA_HOST = settings.OLLAMA_HOST or 'http://localhost:11434'

        client = ollama.Client(host=OLLAMA_HOST)

        try:
            # Пробуем сделать тестовый эмбеддинг, чтобы проверить модель
            client.embeddings(model=EMBEDDING_MODEL, prompt="test")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Ошибка: Модель '{EMBEDDING_MODEL}' не найдена или Ollama недоступна."))
            self.stdout.write("Выполните в терминале: ollama pull nomic-embed-text")
            return

        # ==========================================
        # 2. Индексируем ТАБЛИЦЫ
        # ==========================================
        tables = SchemaTable.objects.filter(is_enabled=True)
        self.stdout.write(f"Найдено {tables.count()} активных таблиц.")

        for table in tables:
            # Если описания нет, мы не можем сделать вектор
            if not table.description_ru:
                self.stdout.write(self.style.WARNING(f"  [SKIP] Таблица {table.table_name}: нет описания"))
                continue

            try:
                # Генерируем вектор
                response = client.embeddings(model=EMBEDDING_MODEL, prompt=table.description_ru)
                vector = response['embedding']

                # Сохраняем в базу
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
                continue  # Пропускаем молча, чтобы не спамить

            try:
                # ВАЖНО: Мы добавляем контекст!
                # Вместо просто "Бюджет", мы векторизуем:
                # "Таблица tv_facts, колонка budget: Фактические расходы на ТВ"
                # Это помогает ИИ отличать "бюджет ТВ" от "бюджета Радио".

                text_to_embed = f"Таблица {col.schema_table.table_name}, колонка {col.column_name}: {col.description_ru}"

                response = client.embeddings(model=EMBEDDING_MODEL, prompt=text_to_embed)
                vector = response['embedding']

                col.embedding = vector
                col.save(update_fields=['embedding'])

                # Выводим точку для прогресса, чтобы не засорять экран
                self.stdout.write(".", ending="")
                self.stdout.flush()

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"\n  [FAIL] Колонка {col.column_name}: {e}"))

        self.stdout.write("\n")
        self.stdout.write(self.style.SUCCESS("Индексация успешно завершена! Теперь 'Маршрутизатор' готов к работе."))