from celery import shared_task
from .models import ChatSession, Message
import logging
from django.conf import settings

# Импорты ai_core
from ai_core.sql_generator import SQLGenerator
from ai_core.security import SQLValidator
from ai_core.db_executor import DatabaseExecutor
from ai_core.chart_generator import ChartGenerator
from ai_core.response_formatter import ResponseFormatter
from ai_core.models import DataSource, SchemaTable

logger = logging.getLogger(__name__)


# Вспомогательное исключение для прерывания
class TaskCancelledException(Exception):
    pass


def check_if_cancelled(session_id, current_task_id):
    """
    (НОВОЕ) Проверяет, не отменил ли пользователь задачу.
    Если в базе current_task_id изменился или исчез - бросаем исключение.
    """
    try:
        session = ChatSession.objects.get(id=session_id)
        # Если ID в базе не совпадает с ID текущей задачи (или он None) -> Стоп
        if str(session.current_task_id) != current_task_id:
            logger.info(f"Задача {current_task_id} отменена пользователем (Check).")
            raise TaskCancelledException()
    except ChatSession.DoesNotExist:
        # Если сессию удалили во время генерации
        raise TaskCancelledException()


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
    logger.info(f"Начинаем обработку.", extra=log_context)

    try:
        # [CHECKPOINT 1] Проверка перед стартом
        check_if_cancelled(session_id, task_id)

        # --- ИНИЦИАЛИЗАЦИЯ ---
        active_datasource = DataSource.objects.filter(is_active=True).first()
        if not active_datasource:
            logger.warning("Нет активного DataSource!")

        allowed_tables_qs = SchemaTable.objects.filter(is_enabled=True)
        if active_datasource:
            allowed_tables_qs = allowed_tables_qs.filter(data_source=active_datasource)
        dynamic_allowed_tables = list(allowed_tables_qs.values_list('table_name', flat=True))

        sql_gen = SQLGenerator(
            model_name=settings.OLLAMA_SQL_MODEL,
            host=settings.OLLAMA_HOST,
            temperature=settings.OLLAMA_SQL_TEMPERATURE
        )
        sql_validator = SQLValidator(allowed_tables=dynamic_allowed_tables)
        db_executor = DatabaseExecutor(datasource=active_datasource)
        chart_gen = ChartGenerator()
        response_formatter = ResponseFormatter(
            model_name=settings.OLLAMA_SUMMARY_MODEL,
            host=settings.OLLAMA_HOST,
            temperature=settings.OLLAMA_TEMPERATURE
        )

        session = ChatSession.objects.get(id=session_id)

    except (ChatSession.DoesNotExist, TaskCancelledException):
        logger.info("Задача остановлена (отмена или удаление сессии).", extra=log_context)
        return
    except Exception as e:
        logger.error(f"Ошибка инициализации: {e}", extra=log_context)
        _save_error_message(session_id, f"Ошибка конфигурации: {e}")
        return

    sql_query = ""
    try:
        # [CHECKPOINT 2] Проверка перед генерацией SQL (Самый долгий этап 1)
        check_if_cancelled(session_id, task_id)

        # --- (ШАГ 1: ГЕНЕРАЦИЯ SQL) ---
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

        # [CHECKPOINT 3] Проверка перед выполнением SQL
        check_if_cancelled(session_id, task_id)

        # --- (ШАГ 3: ВЫПОЛНЕНИЕ SQL) ---
        df = db_executor.execute_query(sql_query)
        log_context['rows_found'] = len(df)

        # [CHECKPOINT 4] Проверка перед генерацией сводки (Самый долгий этап 2)
        check_if_cancelled(session_id, task_id)

        # --- (ШАГ 4: ГРАФИК + СВОДКА) ---
        chart_json = chart_gen.generate_plotly_json(df, user_prompt)
        text_response_raw = response_formatter.get_summary_response(user_prompt, df)

        final_text = response_formatter.format_final_message(text_response_raw, chart_json, df)

        # [CHECKPOINT 5] Финальная проверка перед сохранением
        check_if_cancelled(session_id, task_id)

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

        # Очищаем ID задачи в сессии, так как мы закончили
        session.current_task_id = None
        session.save(update_fields=['current_task_id'])

        logger.info(f"Задача успешно завершена.", extra=log_context)
        return "Task complete"

    except TaskCancelledException:
        logger.warning("Задача была прервана пользователем.", extra=log_context)
        # Мы ничего не сохраняем и просто выходим

    except (PermissionError, ValueError, TimeoutError) as e:
        logger.warning(f"Ошибка валидации: {e}", extra=log_context)
        _save_error_message(session_id, f"Ошибка при обработке запроса: {e}\n\n**Сгенерированный SQL:**\n`{sql_query}`")
        self.request.disable_retries()
        # Очищаем ID задачи
        _clear_task_id(session_id)

    except Exception as e:
        logger.error(f"Неизвестная ошибка: {e}", extra=log_context)
        _save_error_message(session_id, f"Извините, произошла ошибка. Повторяем попытку...")
        _clear_task_id(session_id)
        raise self.retry(exc=e)


def _save_error_message(session_id, error_message):
    try:
        Message.objects.create(session_id=session_id, role='ai', content=error_message)
    except Exception:
        pass


def _clear_task_id(session_id):
    try:
        s = ChatSession.objects.get(id=session_id)
        s.current_task_id = None
        s.save(update_fields=['current_task_id'])
    except:
        pass