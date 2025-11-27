from django.db.utils import OperationalError
import logging
from datetime import datetime
from .models import DataSource, SchemaTable, SchemaColumn
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import URL

logger = logging.getLogger(__name__)


def _has_non_ascii(s: str) -> bool:
    return any(ord(ch) > 127 for ch in s)


def sync_database_schema(datasource: DataSource):
    """
    Подключается к DataSource (используя SQLAlchemy)
    и "наполняет" наши модели SchemaTable/SchemaColumn.
    """
    logger.info(f"Запуск интроспекции для: {datasource.name}")

    db_user = str(datasource.db_user or "")
    db_password = str(datasource.db_password or "")
    db_host = str(datasource.host or "")
    db_name = str(datasource.db_name or "")
    db_port = datasource.port

    logger.info(
        "Параметры подключения: engine=%r user=%r host=%r port=%r db=%r",
        datasource.engine,
        db_user,
        db_host,
        db_port,
        db_name,
    )

    # Предупреждаем, если есть не-ASCII
    for label, value in [
        ("db_user", db_user),
        ("db_host", db_host),
        ("db_name", db_name),
    ]:
        if _has_non_ascii(value):
            logger.warning(
                "Параметр %s содержит не-ASCII символы. На Windows/psycopg2 это "
                "может приводить к UnicodeDecodeError: %r",
                label,
                value,
            )

    try:
        # Формируем URL для SQLAlchemy
        engine_url = URL.create(
            drivername=datasource.engine.replace("django.db.backends.", ""),
            username=db_user,
            password=db_password,
            host=db_host,
            port=db_port,
            database=db_name,
        )

        # Минимальные параметры подключения
        connect_args = {
            "connect_timeout": 5,
        }

        logger.info(f"Создаем SQLAlchemy engine: {engine_url!r}")
        engine = create_engine(engine_url, connect_args=connect_args)

        # ВАЖНО: у тебя падало уже тут, на inspect(engine)
        inspector = inspect(engine)

        logger.info("Пробуем получить список таблиц...")
        table_list = inspector.get_table_names()
        logger.info(f"Найдено {len(table_list)} таблиц: {table_list!r}")

        found_tables = set()
        IGNORED_PREFIXES = [
            # Стандартные Django
            'django_',
            'auth_',

            # Наши приложения
            'users_',
            'chat_',
            'ai_core_',

            # Служебные таблицы Postgres
            'pg_',
            'sql_',

            # Сторонние библиотеки
            'social_',  # если есть social-auth
            'account_',  # если есть allauth
            'easy_',  # если есть easy-thumbnails
            'thumbnail_',
            'celery_',
            'django_celery_',
        ]

        for table_name in table_list:
            # --- (НОВАЯ ПРОВЕРКА) ---
            # Если имя таблицы начинается с ЛЮБОГО из запрещенных префиксов -> пропускаем
            if any(table_name.startswith(prefix) for prefix in IGNORED_PREFIXES):
                continue

            # Специфично для SQLite (иногда создает sqlite_sequence)
            if table_name.startswith('sqlite_'):
                continue
            # ------------------------

            found_tables.add(table_name)

            # 4. Сохраняем Таблицу (дальше код без изменений)
            table_obj, created = SchemaTable.objects.update_or_create(
                data_source=datasource,
                table_name=table_name,
                defaults={'is_enabled': True}
            )

            if created:
                logger.info(f"Найдена новая таблица: {table_name}")

            found_columns = set()

            logger.info(f"Читаем колонки таблицы {table_name}...")
            columns_info = inspector.get_columns(table_name)

            for col in columns_info:
                col_name = str(col.get("name"))
                found_columns.add(col_name)

                try:
                    field_type = str(col.get("type"))
                except UnicodeDecodeError:
                    logger.warning(
                        f"Невозможно декодировать тип колонки {table_name}.{col_name}, "
                        f"использую repr(...)"
                    )
                    field_type = repr(col.get("type"))

                SchemaColumn.objects.update_or_create(
                    schema_table=table_obj,
                    column_name=col_name,
                    defaults={
                        "data_type": field_type,
                        "is_enabled": True,
                    },
                )

            SchemaColumn.objects.filter(schema_table=table_obj).exclude(
                column_name__in=found_columns
            ).delete()

        SchemaTable.objects.filter(data_source=datasource).exclude(
            table_name__in=found_tables
        ).delete()

        datasource.last_inspected = datetime.now()
        datasource.save(update_fields=["last_inspected"])

        logger.info(f"Интроспекция для {datasource.name} успешно завершена.")
        return (True, None)

    except OperationalError as e:
        logger.error(f"Ошибка подключения к {datasource.name}: {e}", exc_info=True)
        return (False, f"Ошибка подключения: {e}")
    except UnicodeDecodeError as e:
        logger.error(
            f"Ошибка декодирования при подключении к {datasource.name}: {e}",
            exc_info=True,
        )
        return (
            False,
            "Ошибка кодировки при подключении. "
            "Скорее всего в имени БД/пользователя/хоста есть символы не в UTF-8. "
            "Попробуй использовать только латиницу и цифры.",
        )
    except Exception as e:
        logger.error(
            f"Неизвестная ошибка при интроспекции {datasource.name}: {e}",
            exc_info=True,
        )
        return (False, f"Неизвестная ошибка: {e}")
