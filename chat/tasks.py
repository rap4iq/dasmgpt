from celery import shared_task
from .models import ChatSession, Message
import pandas as pd
import plotly.express as px
import logging
import re
import json
import numpy as np
from pandas.api.types import is_numeric_dtype
from django.conf import settings
from sqlalchemy import create_engine
import ollama

logger = logging.getLogger(__name__)

# ===================================================================
# 1. DDL (Схема БД)
# ===================================================================
DDL_TV = """
CREATE TABLE tv (
    id SERIAL PRIMARY KEY,
    channel_name VARCHAR(100),   -- Название ТВ канала
    broadcast_date DATE,         -- Дата эфира
    budget DECIMAL(10, 2),       -- Потраченный бюджет
    coverage INT,                -- Охват
    grp DECIMAL(5, 2)            -- Gross Rating Point
);
"""
# (Убедитесь, что вы вставили DDL_RD и DDL_OOH)
DDL_RD = """
CREATE TABLE rd (
    id SERIAL PRIMARY KEY,
    station_name VARCHAR(100),   -- Название радиостанции
    budget DECIMAL(10, 2),       -- Бюджет
    broadcast_period VARCHAR(50),-- Период
    region VARCHAR(100)          -- Регион
);
"""
DDL_OOH = """
CREATE TABLE ooh (
    id SERIAL PRIMARY KEY,
    media_type VARCHAR(100),     -- Тип носителя (билборд, ситилайт)
    city VARCHAR(100),           -- Город
    start_date DATE,             -- Дата начала
    end_date DATE,               -- Дата окончания
    expenses DECIMAL(10, 2)      -- Расходы (синоним budget)
);
"""

FULL_DB_SCHEMA = f"""
{DDL_TV}
{DDL_RD}
{DDL_OOH}
Инструкции:
- 'expenses' в 'ooh' - это то же самое, что 'budget'.
- 'grp' - это 'Gross Rating Point'.
"""

# ===================================================================
# 2. Системные промпты
# ===================================================================
SYSTEM_PROMPT_SQL = f"""
Ты - безмолвный SQL-генератор. Ты *никогда* не общаешься с пользователем.
Твоя ЕДИНСТВЕННАЯ задача - генерировать ОДИН SQL-запрос, который отвечает на вопрос пользователя, используя схему БД.
Ты должен генерировать ТОЛЬКО SQL-код.
НЕ используй Markdown (```sql ... ```). 
НЕ добавляй объяснений. 
НЕ говори "Привет".

СХЕМА БД:
{FULL_DB_SCHEMA}
"""
SYSTEM_PROMPT_SUMMARY = """
Ты - AI-ассистент DasmGPT. 
Твоя задача - написать краткий, дружелюбный текстовый ответ (на русском) для пользователя,
объясняющий данные, которые были получены из БД.
НЕ включай сами данные (JSON) в свой ответ, просто опиши их.
"""



def parse_sql_from_response(response_text: str) -> str:
    response_text = response_text.strip()
    match = re.search(r"```sql\s*(.*?)\s*```", response_text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip().rstrip(';') + ';'
    response_text_upper = response_text.upper()
    if response_text_upper.startswith('SELECT') or response_text_upper.startswith('WITH'):
        return response_text.rstrip(';') + ';'
    logger.error(f"Ollama не вернула SQL. Вместо этого она вернула: {response_text}")
    raise ValueError(f"AI не смог сгенерировать SQL-запрос. Вместо этого он ответил: '{response_text[:100]}...'")



def is_plottable(df: pd.DataFrame) -> bool:
    """
    Проверяет, подходит ли DataFrame для графика (2 колонки, 2-я - числовая)
    """
    if df.empty or len(df.columns) != 2:
        return False

    # Используем "умную" проверку pandas, которая распознает
    # int, float, и Decimal (которые приходят из Postgres)
    if is_numeric_dtype(df.iloc[:, 1]):
        return True

    return False



def detect_chart_type(df: pd.DataFrame, prompt: str) -> str:
    prompt_lower = prompt.lower();
    if "динамика" in prompt_lower: return "line"
    if "доли" in prompt_lower: return "pie"
    if not df.empty and len(df.columns) > 0:
        first_col_name = str(df.columns[0]).lower()
        if 'date' in first_col_name: return "line"
    return "bar"


def generate_plotly_json(df: pd.DataFrame, chart_type: str, title: str) -> str | None:
    """
    Генерирует КРАСИВЫЙ JSON для Plotly.
    """
    try:
        if not is_plottable(df):
            logger.warning("Данные не подходят для построения графика (is_plottable = False)")
            return None

        x_col, y_col = df.columns[0], df.columns[1]

        # Определяем подписи для осей (убираем _ и делаем заглавными)
        labels = {
            x_col: x_col.replace('_', ' ').title(),
            y_col: y_col.replace('_', ' ').title()
        }

        if chart_type == 'line':
            fig = px.line(
                df, x=x_col, y=y_col, title=title, markers=True,
                labels=labels,
                hover_name=x_col,  # Показываем X при наведении
                hover_data={y_col: ':.2f'}  # Форматируем Y (2 знака после запятой)
            )
        elif chart_type == 'pie':
            fig = px.pie(
                df, names=x_col, values=y_col, title=title,
                labels=labels,
                hover_name=x_col
            )
            # Добавляем проценты
            fig.update_traces(textposition='inside', textinfo='percent+label')
        else:  # 'bar'
            fig = px.bar(
                df, x=x_col, y=y_col, title=title,
                labels=labels,
                hover_name=x_col,
                hover_data={y_col: ':.2f'}
            )

        # Общий стиль
        fig.update_layout(
            template="plotly_white",
            title_x=0.5  # Центрируем заголовок
        )
        return fig.to_json()

    except Exception as e:
        logger.error(f"Ошибка при генерации графика Plotly: {e}", exc_info=True)
        return None




@shared_task(bind=True, max_retries=3)
def get_ai_response(self, session_id, user_prompt):
    logger.info(f"[Task ID: {self.request.id}] Начинаем обработку (Ollama CHAT) для сессии {session_id}.")
    MODEL_NAME = 'deepseek-r1:8b'

    try:
        session = ChatSession.objects.get(id=session_id)
        ollama_client = ollama.Client(host='http://localhost:11434')

        # --- ШАГ 1: Генерируем SQL ---
        logger.info(f"[Task ID: {self.request.id}] Звонок 1: Генерация SQL...")
        response_sql_raw = ollama_client.chat(
            model=MODEL_NAME,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT_SQL},
                {'role': 'user', 'content': f"Вопрос: {user_prompt}\nSQL:"}
            ],
            options={'temperature': 0.0}
        )
        sql_query = parse_sql_from_response(response_sql_raw['message']['content'])
        logger.info(f"[Task ID: {self.request.id}] SQL получен: {sql_query}")

        # --- БЕЗОПАСНОСТЬ (ТЗ п. 7) ---
        safe_sql_query = sql_query.strip().upper()
        if not safe_sql_query.startswith('SELECT') and not safe_sql_query.startswith('WITH'):
            logger.warning(
                f"[Task ID: {self.request.id}] НЕДОПУСТИМЫЙ SQL: Запрос был заблокирован (не SELECT/WITH): {sql_query}")
            raise ValueError(
                f"Запрос был заблокирован системой безопасности (не SELECT/WITH). Сгенерированный SQL: `{sql_query}`")
        # --- КОНЕЦ ПРОВЕРКИ БЕЗОПАСНОСТИ ---

        # --- ШАГ 2: Выполняем SQL ---
        df = pd.DataFrame()
        chart_json = None
        try:
            db_config = settings.DATABASES['default']

            if 'sqlite3' in db_config['ENGINE']:
                db_path = db_config['NAME']
                engine_url = f"sqlite:///{db_path}"
            elif 'postgresql' in db_config['ENGINE']:
                db_user = db_config.get('USER', '')
                db_pass = db_config.get('PASSWORD', '')
                db_host = db_config.get('HOST', 'localhost')
                db_port = db_config.get('PORT', '5432')
                db_name = db_config.get('NAME', 'dasmdb')  # Убедитесь, что db_name правильный
                engine_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
            else:
                raise Exception(f"Неподдерживаемый ENGINE базы данных: {db_config['ENGINE']}")

            logger.info(f"Подключение к: {db_host}/{db_name}")
            engine = create_engine(engine_url)

            df = pd.read_sql(sql_query, engine)
            logger.info(f"[Task ID: {self.request.id}] SQL выполнен, получено {df.shape[0]} строк.")

        except Exception as e:
            logger.error(f"[Task ID: {self.request.id}] Ошибка выполнения SQL: {e}", exc_info=True)
            raise ValueError(f"Ошибка при выполнении SQL: {e}\n\n**Сгенерированный SQL:**\n`{sql_query}`")

        # --- ШАГ 3: Генерируем График ---
        if not df.empty:
            chart_type = detect_chart_type(df, user_prompt)
            chart_json = generate_plotly_json(df, chart_type, user_prompt)

        # --- ШАГ 4: Генерируем Текстовый ответ ---
        logger.info(f"[Task ID: {self.request.id}] Звонок 2: Генерация Сводки...")
        data_json = df.head(15).to_json(orient='records')
        summary_user_prompt = f'Вопрос: "{user_prompt}"\nДанные: {data_json}\nТвой краткий ответ:'

        response_summary_raw = ollama_client.chat(
            model=MODEL_NAME,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT_SUMMARY},
                {'role': 'user', 'content': summary_user_prompt}
            ],
            options={'temperature': 0.7}
        )
        text_response = response_summary_raw['message']['content'].strip()

        if not text_response and not df.empty:
            text_response = f"Вот данные по вашему запросу:\n\n {df.to_markdown(index=False)}"

        logger.info(f"[Task ID: {self.request.id}] Сводка получена.")

        # --- ШАГ 5: Сохраняем в БД ---
        Message.objects.create(
            session=session,
            role='ai',
            content=text_response,
            data_payload={
                'plotly_json': chart_json,
                'sql_query': sql_query
            }
        )

        logger.info(f"[Task ID: {self.request.id}] Задача успешно завершена.")
        return "Task complete"

    except Exception as e:
        logger.error(f"[Task ID: {self.request.id}] Ошибка в задаче get_ai_response (Ollama): {e}", exc_info=True)
        try:
            Message.objects.create(
                session_id=session_id,
                role='ai',
                content=f"Извините, при обработке вашего запроса произошла ошибка:\n\n`{str(e)}`"
            )
        except Exception as e_save:
            logger.error(f"[Task ID: {self.request.id}] Не удалось сохранить сообщение об ошибке: {e_save}")

        if "Connection" not in str(e) and "locked" not in str(e):
            self.request.disable_retries()
