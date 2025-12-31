import ollama
import logging
import re
from django.conf import settings
from ai_core.models import SchemaTable, SchemaColumn
from pgvector.django import CosineDistance

logger = logging.getLogger(__name__)


class SQLGenerator:
    """
    Отвечает за "Звонок 1" к Ollama.
    ВЕРСИЯ 3.5: Авто-определение имени модели эмбеддингов.
    """

    def __init__(self, model_name: str, host: str, temperature: float):
        self.model_name = model_name
        self.host = host
        self.temperature = temperature

        # Дефолтное имя
        self.embedding_model = 'nomic-embed-text'

        try:
            self.client = ollama.Client(host=self.host)

            # (НОВОЕ) Пытаемся найти правильное имя модели в списке
            try:
                models_list = self.client.list()
                available_models = [m['model'] for m in models_list['models']]
                for m in available_models:
                    if 'nomic-embed-text' in m:
                        self.embedding_model = m
                        break
                logger.info(f"SQLGenerator использует эмбеддинг-модель: {self.embedding_model}")
            except:
                logger.warning("Не удалось получить список моделей Ollama, используем дефолтное имя 'nomic-embed-text'")

        except Exception as e:
            logger.error(f"Не удалось подключиться к Ollama: {e}")
            raise ConnectionError(f"Ollama недоступна по адресу {host}")

    def _get_query_embedding(self, text: str):
        try:
            response = self.client.embeddings(model=self.embedding_model, prompt=text)
            return response['embedding']
        except Exception as e:
            logger.error(f"Ошибка генерации вектора для запроса (Модель {self.embedding_model}): {e}")
            raise ValueError(f"Не удалось векторизовать запрос. Проверьте модель '{self.embedding_model}'.")

    # ... (Остальные методы: _find_relevant_tables, _build_system_prompt, _parse_sql_from_response, generate_sql) ...
    # ОНИ ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ, КОПИРУЙТЕ ИХ ИЗ ПРОШЛОЙ ВЕРСИИ

    def _find_relevant_tables(self, user_prompt: str, limit: int = 5):
        logger.info(f"Маршрутизатор: Ищу таблицы для '{user_prompt}'...")
        query_vector = self._get_query_embedding(user_prompt)

        relevant_columns_qs = SchemaColumn.objects.filter(
            is_enabled=True,
            embedding__isnull=False
        ).annotate(
            distance=CosineDistance('embedding', query_vector)
        ).order_by('distance')[:15]

        table_ids_list = list(relevant_columns_qs.values_list('schema_table_id', flat=True))
        unique_table_ids = list(set(table_ids_list))

        relevant_tables = SchemaTable.objects.filter(
            id__in=unique_table_ids,
            is_enabled=True,
            data_source__is_active=True
        )

        found_names = [t.table_name for t in relevant_tables]
        logger.info(f"Маршрутизатор: Найдено {len(found_names)} релевантных таблиц: {found_names}")

        if not relevant_tables.exists():
            logger.warning("Маршрутизатор: Векторный поиск не дал результатов! Использую дефолтные таблицы.")
            return SchemaTable.objects.filter(is_enabled=True)[:3]

        return relevant_tables

    def _build_system_prompt(self, user_prompt: str) -> str:
        target_tables = self._find_relevant_tables(user_prompt)

        generated_ddl = []
        instructions = [
            "Ты - SQL-генератор для PostgreSQL.",
            "Твоя задача: сгенерировать ОДИН SQL-запрос, отвечающий на вопрос пользователя.",
            "1. Используй ТОЛЬКО предоставленные ниже таблицы.",
            "2. НЕ используй Markdown (```sql ... ```). Только чистый код.",
            "3. Для поиска текста (VARCHAR) используй 'ILIKE'.",
            "4. ВАЖНО: Если пользователь ищет категорию, ищи варианты на РУССКОМ (ILIKE '%...%') ИЛИ на АНГЛИЙСКОМ (ILIKE '%...%'), используя OR.",
            "5. ПРАВИЛО: Если ты фильтруешь (WHERE) или сортируешь (ORDER BY) по колонке, ты ОБЯЗАН добавить эту колонку в SELECT.",
            "6. Если вопрос 'Где...', включи в SELECT не только локацию, но и ключевые метрики (бюджет, продажи).",
            "\nСХЕМА БД:",
        ]

        for table in target_tables:
            desc = f" ({table.description_ru})" if table.description_ru else ""
            generated_ddl.append(f"-- Таблица: {table.table_name}{desc}")
            generated_ddl.append(f"CREATE TABLE {table.table_name} (")

            enabled_columns = table.columns.filter(is_enabled=True)
            col_defs = []
            for col in enabled_columns:
                c_desc = f" -- {col.description_ru}" if col.description_ru else ""
                col_defs.append(f"  {col.column_name} {col.data_type}{c_desc}")

            generated_ddl.append(",\n".join(col_defs))
            generated_ddl.append(");\n")

        return "\n".join(instructions) + "\n" + "\n".join(generated_ddl)

    def _parse_sql_from_response(self, response_text: str) -> str:
        response_text = response_text.strip()
        match = re.search(r"```sql\s*(.*?)\s*```", response_text, re.DOTALL | re.IGNORECASE)
        if match:
            sql = match.group(1).strip()
        elif response_text.upper().startswith(('SELECT', 'WITH')):
            sql = response_text.strip()
        else:
            logger.error(f"Ollama не вернула SQL. Ответ: {response_text}")
            raise ValueError("AI не смог сгенерировать SQL. Попробуйте переформулировать вопрос.")

        sql = re.sub(r'[\);\s]+$', '', sql)
        return sql + ';'

    def generate_sql(self, user_prompt: str, history: list = None) -> str:
        dynamic_system_prompt = self._build_system_prompt(user_prompt)

        messages_payload = [{'role': 'system', 'content': dynamic_system_prompt}]

        if history:
            messages_payload.extend(history)

        messages_payload.append({'role': 'user', 'content': f"Вопрос: {user_prompt}\nSQL:"})

        logger.info(f"Отправка запроса в LLM...")

        try:
            response_raw = self.client.chat(
                model=self.model_name,
                messages=messages_payload,
                options={'temperature': self.temperature}
            )

            sql_query = self._parse_sql_from_response(response_raw['message']['content'])
            logger.info(f"SQL получен: {sql_query}")
            return sql_query

        except Exception as e:
            logger.error(f"Ошибка LLM: {e}", exc_info=True)
            raise ConnectionError(f"Ошибка генерации: {e}")