import pandas as pd
import logging
from django.conf import settings
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError
from .models import DataSource

logger = logging.getLogger(__name__)

QUERY_ROW_LIMIT = settings.QUERY_ROW_LIMIT
QUERY_TIMEOUT_MS = settings.QUERY_TIMEOUT_MS


class DatabaseExecutor:
    """
    Отвечает за подключение к БД и выполнение SQL.
    Теперь поддерживает динамическое подключение к DataSource.
    """

    def __init__(self, datasource: DataSource = None):
        # Если передан DataSource, используем его. Иначе - default из settings.
        if datasource:
            self.engine_url = self._get_datasource_url(datasource)
        else:
            self.engine_url = self._get_default_url()

        self.engine = create_engine(self.engine_url)

    def _get_datasource_url(self, ds: DataSource) -> URL:
        """Создает URL подключения на основе настроек DataSource из админки"""
        logger.info(f"DatabaseExecutor: Подключение к внешнему источнику '{ds.name}' ({ds.host})")

        driver_map = {
            'django.db.backends.postgresql': 'postgresql',
            'django.db.backends.mysql': 'mysql',
            'django.db.backends.sqlite3': 'sqlite',
        }
        driver = driver_map.get(ds.engine, 'postgresql')

        return URL.create(
            drivername=driver,
            username=ds.db_user,
            password=ds.db_password,
            host=ds.host,
            port=ds.port,
            database=ds.db_name,
            query={"client_encoding": "utf8"} if driver == 'postgresql' else {}
        )

    def _get_default_url(self) -> str:
        """(Старый метод) Подключение к Django DB"""
        try:
            db_config = settings.DATABASES['default']
            # ... (код получения URL из settings, как был раньше) ...
            if 'postgresql' in db_config['ENGINE']:
                return f"postgresql://{db_config['USER']}:{db_config['PASSWORD']}@{db_config['HOST']}:{db_config['PORT']}/{db_config['NAME']}"
            return f"sqlite:///{db_config['NAME']}"
        except Exception:
            return "sqlite:///:memory:"  # Fallback

    def _apply_bodyguard_rules(self, sql_query: str) -> str:
        # (Без изменений - Телохранитель)
        if 'SELECT *' in sql_query.upper():
            raise PermissionError("Запрос заблокирован: `SELECT *` не разрешен.")
        if "LIMIT" not in sql_query.upper():
            sql_query = f"{sql_query.rstrip(';')} LIMIT {QUERY_ROW_LIMIT};"
        return sql_query

    def execute_query(self, sql_query: str) -> pd.DataFrame:
        # (Без изменений - Выполнение)
        try:
            sql_query_safe = self._apply_bodyguard_rules(sql_query)
            logger.info(f"Выполнение SQL: {sql_query_safe[:50]}...")

            with self.engine.connect() as connection:
                if 'postgresql' in str(self.engine_url):
                    connection.execute(text(f"SET statement_timeout = {QUERY_TIMEOUT_MS}"))

                return pd.read_sql(sql_query_safe, connection)

        except Exception as e:
            logger.error(f"Ошибка SQL: {e}", exc_info=True)
            raise