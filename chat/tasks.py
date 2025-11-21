from celery import shared_task
from .models import ChatSession, Message
import logging
from django.conf import settings
from ai_core.sql_generator import SQLGenerator
from ai_core.security import SQLValidator
from ai_core.db_executor import DatabaseExecutor
from ai_core.chart_generator import ChartGenerator
from ai_core.response_formatter import ResponseFormatter
from ai_core.models import DataSource

logger = logging.getLogger(__name__)

# Лимит сообщений для контекста ("Скользящее окно")
HISTORY_LIMIT = 6


@shared_task(
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_kwargs={'max_retries': 3},
    retry_backoff=True,
    retry_backoff_max=600
)
def get_ai_response(self, session_id, user_prompt):
    task_id = self.request.id
    log_context = {'task_id': task_id, 'session_id': session_id}

    try:
        active_datasource = DataSource.objects.filter(is_active=True).first()
        if not active_datasource:
            raise ValueError("Нет активных источников данных (DataSource)!")

        sql_gen = SQLGenerator(
            model_name=settings.OLLAMA_MODEL,
            host=settings.OLLAMA_HOST,
            temperature=settings.OLLAMA_SQL_TEMPERATURE
        )
        db_executor = DatabaseExecutor(datasource=active_datasource)
        sql_validator = SQLValidator(allowed_tables=settings.SQL_ALLOWED_TABLES)
        chart_gen = ChartGenerator()
        response_formatter = ResponseFormatter(
            model_name=settings.OLLAMA_MODEL,
            host=settings.OLLAMA_HOST,
            temperature=settings.OLLAMA_SUMMARY_TEMPERATURE
        )
        session = ChatSession.objects.get(id=session_id)

    except Exception as e:
        logger.error(f"Ошибка инициализации: {e}", extra=log_context)
        _save_error_message(session_id, f"Ошибка конфигурации: {e}")
        return

    sql_query = ""
    try:
        # --- (НОВОЕ) ПОДГОТОВКА ИСТОРИИ ---
        # 1. Получаем последние N сообщений (исключая текущее, которое еще не в БД как "предыдущее")
        # Мы берем их в обратном порядке, чтобы получить "срез", а потом разворачиваем
        last_messages = Message.objects.filter(session=session).order_by('-created_at')[:HISTORY_LIMIT]

        # Разворачиваем в хронологическом порядке
        history_messages = reversed(last_messages)

        formatted_history = []
        for msg in history_messages:
            role = 'user' if msg.role == 'user' else 'assistant'
            content = msg.content

            # Если это ответ ИИ, и там был SQL, полезно добавить его в контекст,
            # чтобы модель видела, как она отвечала раньше (опционально)
            if role == 'assistant' and msg.data_payload and msg.data_payload.get('sql_query'):
                content += f"\n(Сгенерированный ранее SQL: {msg.data_payload['sql_query']})"

            formatted_history.append({
                'role': role,
                'content': content
            })

        logger.info(f"Загружена история: {len(formatted_history)} сообщений.", extra=log_context)
        # ----------------------------------

        # --- (ШАГ 1: ГЕНЕРАЦИЯ SQL С ИСТОРИЕЙ) ---
        # Передаем formatted_history в генератор
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
        logger.warning(f"Ошибка валидации/SQL: {e}", extra=log_context)
        _save_error_message(session_id, f"Ошибка при обработке запроса: {e}\n\n**Сгенерированный SQL:**\n`{sql_query}`")
        self.request.disable_retries()

    except Exception as e:
        logger.error(f"Неизвестная ошибка: {e}", extra=log_context)
        _save_error_message(session_id, f"Произошла ошибка. Повторяем попытку...")
        raise self.retry(exc=e)


def _save_error_message(session_id, error_message):
    try:
        Message.objects.create(session_id=session_id, role='ai', content=error_message)
    except:
        pass