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

@shared_task(
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError),  # (п. 8) Повторяем ошибки сети, Ollama и "Телохранителя"
    retry_kwargs={'max_retries': 3},
    retry_backoff=True,
    retry_backoff_max=600  # Макс. 10 минут
)
def get_ai_response(self, session_id, user_prompt):
    """
    Главная Celery-задача, которая управляет всем процессом.
    """
    task_id = self.request.id
    # (п. 7) Структурированное логирование
    log_context = {'task_id': task_id, 'session_id': session_id, 'prompt': user_prompt}
    logger.info(f"Начинаем рефакторинг-обработку.", extra=log_context)

    try:
        # --- (НОВАЯ ЛОГИКА ВЫБОРА БАЗЫ) ---
        # 1. Ищем активный источник данных (берем первый попавшийся активный)
        active_datasource = DataSource.objects.filter(is_active=True).first()

        if not active_datasource:
            raise ValueError("Нет активных источников данных (DataSource) в админке! ИИ не знает, где искать данные.")

        logger.info(f"Используем источник данных: {active_datasource.name}", extra=log_context)

        # 2. Инициализируем сервисы
        sql_gen = SQLGenerator(
            model_name=settings.OLLAMA_MODEL,
            host=settings.OLLAMA_HOST,
            temperature=settings.OLLAMA_SQL_TEMPERATURE
        )

        # Передаем найденный datasource в исполнитель!
        db_executor = DatabaseExecutor(datasource=active_datasource)

        sql_validator = SQLValidator(
            allowed_tables=settings.SQL_ALLOWED_TABLES)  # (Можно обновить логику whitelist позже)
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
        return  # Останавливаемся

    sql_query = ""  # Инициализируем для блока 'except'
    try:
        # --- (ШАГ 1: ГЕНЕРАЦИЯ SQL) ---
        sql_query = sql_gen.generate_sql(user_prompt)
        log_context['sql'] = sql_query

        # --- (ШАГ 2: БЕЗОПАСНОСТЬ) ---
        sql_validator.validate_sql_safety(sql_query)

        # --- (ШАГ 3: ВЫПОЛНЕНИЕ SQL) ---
        df = db_executor.execute_query(sql_query)
        log_context['rows_found'] = len(df)

        # --- (ШАГ 4: ГРАФИК + СВОДКА) ---
        chart_json = chart_gen.generate_plotly_json(df, user_prompt)
        text_response_raw = response_formatter.get_summary_response(user_prompt, df)

        # Собираем финальный текст (добавляем Markdown-таблицу, если нужно)
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
        # (п. 8) Ошибки SQL, Безопасности или "Телохранителя" - НЕ повторяем.
        logger.warning(f"Ошибка валидации, SQL или Тайм-аута: {e}", extra=log_context)
        _save_error_message(session_id, f"Ошибка при обработке запроса: {e}\n\n**Сгенерированный SQL:**\n`{sql_query}`")
        self.request.disable_retries()  # Повторять бессмысленно

    except Exception as e:
        # (п. 8) Все остальные ошибки (БД, Celery) - МОЖНО повторить
        logger.error(f"Неизвестная ошибка в get_ai_response: {e}", extra=log_context)
        _save_error_message(session_id,
                            f"Извините, при обработке вашего запроса произошла неизвестная ошибка. Повторяем попытку...")
        raise self.retry(exc=e)


def _save_error_message(session_id: int, error_message: str):
    """(п. 1) Вспомогательная функция для сохранения сообщений об ошибках."""
    try:
        Message.objects.create(
            session_id=session_id,
            role='ai',
            content=f"{error_message}"
        )
    except Exception as e_save:
        logger.error(f"Не удалось даже сохранить сообщение об ошибке для сессии {session_id}: {e_save}")