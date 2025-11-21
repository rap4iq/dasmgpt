import ollama
import logging
import re
from django.conf import settings
from ai_core.models import SchemaTable, SchemaColumn

# Импорт для векторного поиска
from pgvector.django import CosineDistance

logger = logging.getLogger(__name__)


class SQLGenerator:
    """
    Отвечает за "Звонок 1" к Ollama.
    ВЕРСИЯ 3.1: Исправлен баг с distinct() после slice.
    """

    def __init__(self, model_name: str, host: str, temperature: float):
        self.model_name = model_name
        self.host = host
        self.temperature = temperature
        self.embedding_model = 'nomic-embed-text'

        try:
            self.client = ollama.Client(host=self.host)
            # Простая проверка
            # self.client.list() # Можно закомментировать для ускорения
        except Exception as e:
            logger.error(f"Не удалось подключиться к Ollama: {e}")
            raise ConnectionError(f"Ollama недоступна по адресу {host}")

    def _get_query_embedding(self, text: str):
        """Превращает вопрос пользователя в вектор."""
        try:
            response = self.client.embeddings(model=self.embedding_model, prompt=text)
            return response['embedding']
        except Exception as e:
            logger.error(f"Ошибка генерации вектора для запроса: {e}")
            raise ValueError("Не удалось векторизовать запрос. Проверьте, скачана ли модель 'nomic-embed-text'.")

    def _find_relevant_tables(self, user_prompt: str, limit: int = 5):
        """
        (СЕРДЦЕ МАРШРУТИЗАТОРА)
        Ищет наиболее подходящие таблицы с помощью векторного поиска.
        """
        logger.info(f"Маршрутизатор: Ищу таблицы для '{user_prompt}'...")

        # 1. Получаем вектор вопроса
        query_vector = self._get_query_embedding(user_prompt)

        # 2. Ищем похожие КОЛОНКИ
        relevant_columns_qs = SchemaColumn.objects.filter(
            is_enabled=True,
            embedding__isnull=False
        ).annotate(
            distance=CosineDistance('embedding', query_vector)
        ).order_by('distance')[:15]  # Берем топ-15 самых похожих колонок

        # 3. (ИСПРАВЛЕНО) Собираем ID таблиц В PYTHON, а не в БД
        # Django запрещает делать .distinct() после среза [:15].
        # Поэтому мы сначала извлекаем список ID, а потом делаем set()
        table_ids_list = list(relevant_columns_qs.values_list('schema_table_id', flat=True))
        unique_table_ids = list(set(table_ids_list))

        # 4. Получаем сами таблицы по уникальным ID
        relevant_tables = SchemaTable.objects.filter(
            id__in=unique_table_ids,
            is_enabled=True,
            data_source__is_active=True
        )

        # Логируем, что мы нашли (для отладки)
        found_names = [t.table_name for t in relevant_tables]
        logger.info(f"Маршрутизатор: Найдено {len(found_names)} релевантных таблиц: {found_names}")

        if not relevant_tables.exists():
            logger.warning("Маршрутизатор: Векторный поиск не дал результатов! Использую дефолтные таблицы.")
            return SchemaTable.objects.filter(is_enabled=True)[:3]

        return relevant_tables

    def _build_system_prompt(self, user_prompt: str) -> str:
        """
        Строит DDL-промпт ДИНАМИЧЕСКИ.
        """
        # 1. Запускаем Маршрутизатор
        target_tables = self._find_relevant_tables(user_prompt)

        generated_ddl = []
        instructions = [
            "Ты — безмолвный генератор SQL-запросов.",
            "Твоя единственная задача — вывести ОДИН корректный SQL-запрос на PostgreSQL.",
            "Ты НЕ ОБЩАЕШЬСЯ с пользователем.",
            "Ты НЕ ДОЛЖЕН писать текст, комментарии, рассуждения, объяснения или разговоры.",
            "ТЫ НИКОГДА НЕ ПИШЕШЬ НИ ОДНОГО СЛОВА, КРОМЕ SQL.",
            "Если вопрос содержит условия, фильтры или сортировки — ОБЯЗАТЕЛЬНО добавь эти поля в SELECT.",
            "Используй только таблицы и колонки, которые я тебе даю ниже.",
            "Никогда не придумывай таблицы или поля.",
            "Все текстовые фильтры выполняй через ILIKE с процентами: ILIKE '%значение%'.",
            "Не используй Markdown.",
            "Не используй обратные кавычки ```.",
            "Не используй TRY/CATCH, не используй функции, которых нет в PostgreSQL.",
            "Никаких комментариев (не используй -- или /* */).",
            "Если в ответе будет хоть одно слово, не относящееся к SQL — это считается ошибкой.",
            "Выводи только SQL без точки в конце, без лишних символов."
        ]

        for table in target_tables:
            # ... (код генерации DDL без изменений) ...
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

    def _parse_sql_from_response(self, text: str) -> str:
        text = text.strip()

        # 1. Забрать всё, что начинается с SELECT или WITH (главное правило)
        match = re.search(r"(SELECT|WITH)\s+.*", text, re.IGNORECASE | re.DOTALL)
        if match:
            sql = match.group(0).strip()
            return sql.rstrip(";") + ";"

        # 2. Второй шанс — если модель всё же сделала блок ```sql
        match = re.search(r"```sql\s*(.*?)\s*```", text, re.IGNORECASE | re.DOTALL)
        if match:
            sql = match.group(1).strip()
            return sql.rstrip(";") + ";"

        # 3. Ни SELECT, ни WITH → это ошибка
        raise ValueError(f"Модель не вернула SQL. Ответ: {text}")

    def generate_sql(self, user_prompt: str, history: list = None) -> str:
        """
        Главный метод.
        """
        # 1. Динамически строим промпт
        dynamic_system_prompt = self._build_system_prompt(user_prompt)

        messages_payload = [{'role': 'system', 'content': dynamic_system_prompt}]

        if history:
            messages_payload.extend(history)

        messages_payload.append({'role': 'user', 'content': f"Вопрос: {user_prompt}\nSQL:"})

        logger.info(f"Отправка запроса в LLM (контекст ограничен релевантными таблицами)...")

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