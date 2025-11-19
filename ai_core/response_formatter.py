import pandas as pd
import ollama
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class ResponseFormatter:
    """
    Отвечает за "Звонок 2" к Ollama. (п. 1, 3, 6)
    """

    def __init__(self, model_name: str, host: str, temperature: float):
        self.model_name = model_name
        self.host = host
        self.temperature = temperature
        try:
            self.client = ollama.Client(host=self.host)
        except Exception as e:
            logger.error(f"Не удалось подключиться к Ollama по адресу {host}: {e}")
            raise ConnectionError(f"Не удалось подключиться к Ollama. Убедитесь, что Ollama запущена по адресу {host}.")

        self.system_prompt = """
Ты - AI-ассистент DasmGPT. 
Твоя задача - написать краткий, дружелюбный текстовый ответ (на русском) для пользователя,
объясняющий данные, которые были получены из БД.
НЕ включай сами данные (JSON) в свой ответ, просто опиши их.
"""

    def get_summary_response(self, user_prompt: str, df: pd.DataFrame) -> str:
        """
        Главный метод. Делает "Звонок 2" (Сводка).
        (п. 10 - пока синхронно)
        """
        logger.info(f"Звонок 2 (ResponseFormatter): Генерация Сводки...")

        # (п. 11) Берем только 'head', чтобы не перегружать ИИ
        data_json = df.head(15).to_json(orient='records')

        summary_user_prompt = f"""
        Вопрос пользователя был: "{user_prompt}"
        Вот данные, которые мы получили из БД (в JSON):
        {data_json}

        Твой краткий текстовый ответ:
        """

        try:
            response_raw = self.client.chat(
                model=self.model_name,
                messages=[
                    {'role': 'system', 'content': self.system_prompt},
                    {'role': 'user', 'content': summary_user_prompt}
                ],
                options={'temperature': self.temperature}
            )
            text_response = response_raw['message']['content'].strip()
            logger.info(f"Сводка получена.")
            return text_response

        except Exception as e:
            logger.error(f"Ошибка при обращении к Ollama (Сводка): {e}", exc_info=True)
            raise ConnectionError(f"Ошибка подключения к Ollama: {e}")

    def format_final_message(self, text_response: str, chart_json: str | None, df: pd.DataFrame) -> str:
        """
        (п. 5 - Тестируемо)
        Добавляем Markdown-таблицу, если нет графика.
        """
        if not text_response and not df.empty:
            text_response = f"Вот данные по вашему запросу:"

        if not chart_json and not df.empty:
            text_response += f"\n\n{df.to_markdown(index=False)}"

        return text_response