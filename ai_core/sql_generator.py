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
    ВЕРСИЯ 3.5: Добавлены кавычки для таблиц и колонок (Postgres Case-Sensitivity).
    """

    def __init__(self, model_name: str, host: str, temperature: float):
        self.model_name = model_name
        self.host = host
        self.temperature = temperature
        self.embedding_model = 'nomic-embed-text'  # Дефолтное значение

        try:
            self.client = ollama.Client(host=self.host)

            # Пытаемся найти правильное имя модели в списке
            try:
                models_list = self.client.list()
                available_models = [m['model'] for m in models_list['models']]
                for m in available_models:
                    if 'nomic-embed-text' in m:
                        self.embedding_model = m
                        break
            except:
                pass  # Используем дефолт

        except Exception as e:
            logger.error(f"Не удалось подключиться к Ollama: {e}")
            raise ConnectionError(f"Ollama недоступна по адресу {host}")

    def _get_query_embedding(self, text: str):
        try:
            response = self.client.embeddings(model=self.embedding_model, prompt=text)
            return response['embedding']
        except Exception as e:
            logger.error(f"Ошибка генерации вектора: {e}")
            raise ValueError("Не удалось векторизовать запрос.")

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

        # (ВАЖНО) Если ничего не нашли по колонкам, ищем по именам таблиц (резерв)
        if not relevant_tables.exists():
            # Простой поиск по вхождению слов (без векторов, как план Б)
            prompt_words = user_prompt.lower().split()
            potential_ids = []
            for word in prompt_words:
                if len(word) > 3:
                    matches = SchemaTable.objects.filter(
                        is_enabled=True,
                        table_name__icontains=word,
                        data_source__is_active=True
                    ).values_list('id', flat=True)
                    potential_ids.extend(matches)

            if potential_ids:
                relevant_tables = SchemaTable.objects.filter(id__in=potential_ids)
                logger.info(f"Маршрутизатор (Fallback): Найдено по имени: {[t.table_name for t in relevant_tables]}")
            else:
                logger.warning("Маршрутизатор: Ничего не найдено. Использую дефолтные таблицы.")
                return SchemaTable.objects.filter(is_enabled=True)[:3]

        return relevant_tables

    def _build_system_prompt(self, user_prompt: str) -> str:
        target_tables = self._find_relevant_tables(user_prompt)

        generated_ddl = []
        instructions = [
            "Ты - SQL-генератор для PostgreSQL.",
            "Твоя задача: сгенерировать ОДИН SQL-запрос.",
            "1. Используй ТОЛЬКО предоставленные ниже таблицы.",
            "2. НЕ используй Markdown. Только чистый код.",
            "3. Для поиска текста используй 'ILIKE'.",
            "4. ВАЖНО: Названия таблиц и колонок могут быть в разном регистре.",
            "   ВСЕГДА используй двойные кавычки для имен таблиц и колонок (например: SELECT \"Title\" FROM \"YouTubeVideos\").",
            # <--- НОВАЯ ИНСТРУКЦИЯ
            "5. Если фильтруешь/сортируешь по колонке, добавь её в SELECT.",
            "\nСХЕМА БД:",
        ]

        for table in target_tables:
            desc = f" ({table.description_ru})" if table.description_ru else ""

            # (ИЗМЕНЕНО) Оборачиваем имя таблицы в кавычки прямо в промпте
            table_name_quoted = f'"{table.table_name}"'

            generated_ddl.append(f"-- Таблица: {table_name_quoted}{desc}")
            generated_ddl.append(f"CREATE TABLE {table_name_quoted} (")

            enabled_columns = table.columns.filter(is_enabled=True)
            col_defs = []
            for col in enabled_columns:
                c_desc = f" -- {col.description_ru}" if col.description_ru else ""

                # (ИЗМЕНЕНО) Оборачиваем имя колонки в кавычки
                col_name_quoted = f'"{col.column_name}"'

                col_defs.append(f"  {col_name_quoted} {col.data_type}{c_desc}")

            generated_ddl.append(",\n".join(col_defs))
            generated_ddl.append(");\n")

        return "\n".join(instructions) + "\n" + "\n".join(generated_ddl)

    def _parse_sql_from_response(self, response_text: str) -> str:
        response_text = response_text.strip()
        match = re.search(r"```sql\s*(.*?)\s*```", response_text, re.DOTALL | re.IGNORECASE)
        if match: return match.group(1).strip().rstrip(';') + ';'
        if response_text.upper().startswith(('SELECT', 'WITH')): return response_text.rstrip(';') + ';'

        # Попытка найти SELECT если нет markdown
        match_select = re.search(r"(SELECT .*?;)", response_text, re.DOTALL | re.IGNORECASE)
        if match_select:
            return match_select.group(1).strip()

        logger.error(f"Ollama не вернула SQL. Ответ: {response_text}")
        raise ValueError("AI не смог сгенерировать SQL. Ответ не содержит кода.")

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
            # Доп. очистка от мусора
            sql_query = re.sub(r'[\);\s]+$', '', sql_query) + ';'

            logger.info(f"SQL получен: {sql_query}")
            return sql_query

        except Exception as e:
            logger.error(f"Ошибка LLM: {e}", exc_info=True)
            raise ConnectionError(f"Ошибка генерации: {e}")