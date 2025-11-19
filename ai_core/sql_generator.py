import ollama
import logging
import re
from ai_core.models import SchemaTable, SchemaColumn

logger = logging.getLogger(__name__)


class SQLGenerator:
    def __init__(self, model_name: str, host: str, temperature: float):
        self.model_name = model_name
        self.host = host
        self.temperature = temperature
        try:
            self.client = ollama.Client(host=self.host)
            self.client.list()
        except Exception as e:
            logger.error(f"Не удалось подключиться к Ollama по адресу {host}: {e}")
            raise ConnectionError(f"Не удалось подключиться к Ollama. Убедитесь, что Ollama запущена по адресу {host}.")

        # (ИЗМЕНЕНО) Теперь мы "строим" промпт динамически
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        """
        (ПОЛНОСТЬЮ ПЕРЕПИСАНО)
        "Строит" DDL-схему (промпт), "читая" ТОЛЬКО "включенные"
        таблицы и колонки из "Куратора" (БД Django).
        """
        logger.info("SQLGenerator: Загрузка " " схемы из БД...")

        # 1. Получаем все "включенные" таблицы (п. 1 "Куратор")
        enabled_tables = SchemaTable.objects.filter(
            is_enabled=True,
            data_source__is_active=True  # (Берем только из активных источников)
        )

        if not enabled_tables.exists():
            logger.error("В 'Кураторе' (ai_core/SchemaTable) нет 'включенных' таблиц.")
            raise ValueError("Ошибка конфигурации: В 'Кураторе' нет активных таблиц.")

        generated_ddl = []
        instructions = [
            "Ты - безмолвный SQL-генератор. Ты *никогда* не общаешься с пользователем.",
            "Твоя ЕДИНСТВЕННАЯ задача - генерировать ОДИН SQL-запрос, который отвечает на вопрос пользователя, используя схему БД.",
            "Ты должен генерировать ТОЛЬКО SQL-код.",
            "НЕ используй Markdown (```sql ... ```).",
            "НЕ добавляй объяснений. НЕ говори 'Привет'.",
            "Ты должен использовать диалект PostgreSQL.",
            "\nСХЕМА БД (ТОЛЬКО 'ВКЛЮЧЕННЫЕ' ТАБЛИЦЫ И КОЛОНКИ):",
        ]

        # 2. "Собираем" DDL "на лету"
        for table in enabled_tables:
            # (п. 2 "Маршрутизатор") Добавляем описание таблицы
            if table.description_ru:
                generated_ddl.append(f"-- Таблица: {table.table_name} ({table.description_ru})")
            else:
                generated_ddl.append(f"-- Таблица: {table.table_name}")

            generated_ddl.append(f"CREATE TABLE {table.table_name} (")

            # 3. Получаем "включенные" колонки (п. 1 "Куратор")
            enabled_columns = table.columns.filter(is_enabled=True)
            col_definitions = []

            for col in enabled_columns:
                col_def = f"  {col.column_name} {col.data_type}"
                # (п. 3 "Семантический слой") Добавляем описание колонки
                if col.description_ru:
                    col_def += f" -- {col.description_ru}"
                col_definitions.append(col_def)

            if not col_definitions:
                # Таблица "включена", но ни одна колонка не "включена"
                continue  # Пропускаем эту таблицу

            generated_ddl.append(",\n".join(col_definitions))
            generated_ddl.append(");\n")

        # 4. Собираем финальный промпт
        final_prompt = "\n".join(instructions) + "\n" + "\n".join(generated_ddl)

        # (п. 7) Логируем только часть промпта (он может быть ОЧЕНЬ большим)
        logger.info(f"SQLGenerator:  Курируемая  схема успешно загружена. (Размер: {len(final_prompt)} байт)")

        return final_prompt

    def _parse_sql_from_response(self, response_text: str) -> str:
        """
        Извлекает чистый SQL из ответа Ollama.
        (Без изменений)
        """
        response_text = response_text.strip()

        match = re.search(r"```sql\s*(.*?)\s*```", response_text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip().rstrip(';') + ';'

        response_text_upper = response_text.upper()
        if response_text_upper.startswith('SELECT') or response_text_upper.startswith('WITH'):
            return response_text.rstrip(';') + ';'

        logger.error(f"Ollama не вернула SQL. Вместо этого она вернула: {response_text}")
        raise ValueError(f"AI не смог сгенерировать SQL-запрос. Вместо этого он ответил: '{response_text[:100]}...'")

    def generate_sql(self, user_prompt: str) -> str:
        """
        Главный метод. Делает "Звонок 1".
        (Без изменений)
        """
        logger.info(f"Звонок 1 (SQLGenerator): Генерация SQL для промпта: {user_prompt}")

        try:
            response_raw = self.client.chat(
                model=self.model_name,
                messages=[
                    {'role': 'system', 'content': self.system_prompt},
                    {'role': 'user', 'content': f"Вопрос: {user_prompt}\nSQL:"}
                ],
                options={'temperature': self.temperature}
            )

            sql_query = self._parse_sql_from_response(response_raw['message']['content'])
            logger.info(f"SQL получен: {sql_query}")
            return sql_query

        except Exception as e:
            logger.error(f"Ошибка при обращении к Ollama (SQL): {e}", exc_info=True)
            raise ConnectionError(f"Ошибка подключения к Ollama: {e}")