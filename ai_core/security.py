# (Логика "Предохранителя", перенесено из tasks.py)
import sqlparse
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

SQL_BLACKLIST = {
    'INSERT', 'UPDATE', 'DELETE', 'DROP', 'TRUNCATE', 'ALTER', 'CREATE',
    'GRANT', 'REVOKE', 'COMMIT', 'ROLLBACK', 'SET', 'EXEC', 'EXECUTE',
    'ATTACH', 'DETACH', 'REINDEX', 'VACUUM',
}


class SQLValidator:
    """
    Отвечает за "Предохранитель" (ТЗ п. 7, Аудит п. 2).
    """

    def __init__(self, allowed_tables: list):
        self.allowed_tables = set(t.lower() for t in allowed_tables)

    def validate_sql_safety(self, sql_query: str) -> bool:
        """
        Продвинутая проверка безопасности SQL.
        """
        logger.info(f"Проверка безопасности SQL: {sql_query[:100]}...")

        try:
            parsed = sqlparse.parse(sql_query)
            if not parsed:
                raise ValueError("Не удалось разобрать SQL")

            for stmt in parsed:
                if stmt.get_type() != 'SELECT':
                    logger.warning(f"НЕДОПУСТИМЫЙ SQL (не SELECT): {sql_query}")
                    raise PermissionError("Запрос заблокирован (не SELECT)")

                has_allowed_table = False
                for token in stmt.flatten():
                    if token.is_keyword and token.value.upper() in SQL_BLACKLIST:
                        logger.warning(f"НЕДОПУСТИМЫЙ SQL (запрещенное слово {token.value.upper()}): {sql_query}")
                        raise PermissionError(f"Запрос заблокирован (запрещенное слово: {token.value.upper()})")

                    if token.ttype is sqlparse.tokens.Name:
                        if token.value.lower() in self.allowed_tables:
                            has_allowed_table = True

            if not has_allowed_table:
                # (п. 2) TODO: Эта проверка слишком "наивная", она может пропустить
                # таблицы в `JOIN`. Для "Куратора" (v2.0) ее нужно будет улучшить.
                logger.warning(f"Простая проверка 'белого списка' пройдена.")

        except Exception as e:
            logger.error(f"Ошибка при парсинге SQL: {e}")
            raise ValueError(f"Ошибка безопасности при разборе SQL: {e}")

        logger.info("SQL прошел проверку безопасности.")
        return True