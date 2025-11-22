from celery import shared_task
from .models import ChatSession, Message
import logging
from django.conf import settings
from ai_core.sql_generator import SQLGenerator
from ai_core.security import SQLValidator
from ai_core.db_executor import DatabaseExecutor
from ai_core.chart_generator import ChartGenerator
from ai_core.response_formatter import ResponseFormatter
from ai_core.models import DataSource, SchemaTable

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_kwargs={'max_retries': 3},
    retry_backoff=True,
    retry_backoff_max=600
)
def get_ai_response(self, session_id, user_prompt):
    task_id = self.request.id
    log_context = {'task_id': task_id, 'session_id': session_id, 'prompt': user_prompt}
    logger.info(f"Начинаем обработку.", extra=log_context)

    try:
        logger.info("Инициализация сервисов ai_core", extra=log_context)

        # 1. Находим активный источник данных
        active_datasource = DataSource.objects.filter(is_active=True).first()
        if not active_datasource:
            # Если нет источника, пробуем работать без него (на дефолтной БД),
            # но лучше залогировать предупреждение.
            logger.warning("Нет активного DataSource, используем default подключение.")

        # 2. Получаем список разрешенных таблиц ДИНАМИЧЕСКИ из базы
        # (Вместо settings.SQL_ALLOWED_TABLES)
        allowed_tables_qs = SchemaTable.objects.filter(is_enabled=True)
        if active_datasource:
            allowed_tables_qs = allowed_tables_qs.filter(data_source=active_datasource)

        # Превращаем QuerySet в список строк ['tv', 'rd', 'ooh']
        dynamic_allowed_tables = list(allowed_tables_qs.values_list('table_name', flat=True))

        if not dynamic_allowed_tables:
            logger.warning("Внимание: Список разрешенных таблиц пуст! SQLValidator будет блокировать всё.")

        # --- ИНИЦИАЛИЗАЦИЯ КЛАССОВ ---

        sql_gen = SQLGenerator(
            model_name=settings.OLLAMA_SQL_MODEL,
            host=settings.OLLAMA_HOST,
            temperature=settings.OLLAMA_SQL_TEMPERATURE
        )

        # Передаем динамический список таблиц в Валидатор
        sql_validator = SQLValidator(allowed_tables=dynamic_allowed_tables)

        # Передаем активный источник в Исполнитель
        db_executor = DatabaseExecutor(datasource=active_datasource)

        chart_gen = ChartGenerator()

        response_formatter = ResponseFormatter(
            model_name=settings.OLLAMA_MODEL,
            host=settings.OLLAMA_HOST,
            temperature=settings.OLLAMA_SUMMARY_TEMPERATURE
        )

        session = ChatSession.objects.get(id=session_id)

    except (ChatSession.DoesNotExist) as e:
        logger.error(f"Критическая ошибка: Сессия {session_id} не найдена.", extra=log_context)
        self.request.disable_retries()
        return
    except (ConnectionError) as e:
        logger.error(f"Критическая ошибка подключения: {e}", extra=log_context)
        _save_error_message(session_id, f"Ошибка подключения к AI-сервисам. Повторяем попытку...")
        raise self.retry(exc=e)

    sql_query = ""
    try:
        # --- (ШАГ 1: ГЕНЕРАЦИЯ SQL) ---
        # Получаем историю для контекста
        last_messages = Message.objects.filter(session=session).order_by('-created_at')[:6]
        history_messages = reversed(last_messages)
        formatted_history = []
        for msg in history_messages:
            role = 'user' if msg.role == 'user' else 'assistant'
            content = msg.content
            if role == 'assistant' and msg.data_payload and msg.data_payload.get('sql_query'):
                content += f"\n(SQL: {msg.data_payload['sql_query']})"
            formatted_history.append({'role': role, 'content': content})

        sql_query = sql_gen.generate_sql(user_prompt, history=formatted_history)
        log_context['sql'] = sql_query

        # --- (ШАГ 2: БЕЗОПАСНОСТЬ) ---
        sql_validator.validate_sql_safety(sql_query)

        # --- (ШАГ 3: ВЫПОЛНЕНИЕ SQL) ---
        df = db_executor.execute_query(sql_query)
        log_context['rows_found'] = len(df)

        # --- (ШАГ 4: ГРАФИК + СВОДКА) ---
        chart_json = chart_gen.generate_plotly_json(df, user_prompt)
        text_response_raw = response_formatter.get_summary_response(user_prompt, df)

        final_text = response_formatter.format_final_message(text_response_raw, chart_json, df)

        # --- (ШАГ 5: СОХРАНЕНИЕ) ---
        Message.objects.create(
            session=session,
            role='ai',
            content=final_text,
            data_payload={
                'plotly_json': chart_json,
                'sql_query': sql_query
            }
        )

        logger.info(f"Задача успешно завершена.", extra=log_context)
        return "Task complete"

    except (PermissionError, ValueError, TimeoutError) as e:
        logger.warning(f"Ошибка валидации или SQL: {e}", extra=log_context)
        _save_error_message(session_id, f"Ошибка при обработке запроса: {e}\n\n**Сгенерированный SQL:**\n`{sql_query}`")
        self.request.disable_retries()

    except Exception as e:
        logger.error(f"Неизвестная ошибка: {e}", extra=log_context)
        _save_error_message(session_id, f"Извините, произошла ошибка. Повторяем попытку...")
        raise self.retry(exc=e)


def _save_error_message(session_id: int, error_message: str):
    try:
        Message.objects.create(session_id=session_id, role='ai', content=error_message)
    except Exception:
        pass