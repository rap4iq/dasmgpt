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
    Поддерживает динамическое подключение к DataSource.
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

        # client_encoding через query для PostgreSQL — нормальный вариант
        query = {"client_encoding": "utf8"} if driver == 'postgresql' else {}

        return URL.create(
            drivername=driver,
            username=ds.db_user,
            password=ds.db_password,
            host=ds.host,
            port=ds.port,
            database=ds.db_name,
            query=query,
        )

    def _get_default_url(self) -> str:
        """(Старый метод) Подключение к Django DB"""
        try:
            db_config = settings.DATABASES['default']
            engine = db_config['ENGINE']

            if 'postgresql' in engine:
                user = db_config.get('USER', '')
                password = db_config.get('PASSWORD', '')
                host = db_config.get('HOST', '') or 'localhost'
                port = db_config.get('PORT', '') or 5432
                name = db_config.get('NAME', '')
                return f"postgresql://{user}:{password}@{host}:{port}/{name}"

            if 'sqlite3' in engine:
                name = db_config.get('NAME', ':memory:')
                return f"sqlite:///{name}"

            # Fallback — можно расширить под другие драйверы
            return "sqlite:///:memory:"
        except Exception as e:
            logger.error(f"Ошибка формирования default URL БД: {e}", exc_info=True)
            return "sqlite:///:memory:"  # Fallback

    def _apply_bodyguard_rules(self, sql_query: str) -> str:
        """
        Телохранитель:
        - запрещает SELECT *
        - гарантирует наличие LIMIT
        """
        upper_sql = sql_query.upper()

        if 'SELECT *' in upper_sql:
            raise PermissionError("Запрос заблокирован: `SELECT *` не разрешен.")

        if "LIMIT" not in upper_sql:
            sql_query = f"{sql_query.rstrip(';')} LIMIT {QUERY_ROW_LIMIT};"

        return sql_query

    def execute_query(self, sql_query: str) -> pd.DataFrame:
        """
        Выполняет безопасный SQL и возвращает DataFrame.
        Использует SQLAlchemy 2.x + pandas.read_sql_query + text().
        """
        try:
            sql_query_safe = self._apply_bodyguard_rules(sql_query)
            logger.info(f"Выполнение SQL: {sql_query_safe[:200]}...")

            with self.engine.connect() as connection:
                # Для PostgreSQL задаём таймаут выполнения запроса
                if 'postgresql' in str(self.engine_url):
                    connection.execute(text(f"SET statement_timeout = {QUERY_TIMEOUT_MS}"))

                # ВАЖНО: оборачиваем строку в text() для SQLAlchemy 2.x
                stmt = text(sql_query_safe)
                df = pd.read_sql_query(stmt, con=connection)

            return df

        except OperationalError as e:
            logger.error(f"Ошибка подключения к БД: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Ошибка SQL: {e}", exc_info=True)
            raise
