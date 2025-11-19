import pandas as pd
import plotly.express as px
import logging
from pandas.api.types import is_numeric_dtype

logger = logging.getLogger(__name__)


class ChartGenerator:
    """
    Отвечает за всю логику, связанную с графиками.
    (п. 1, 4, 5)
    """

    def _is_plottable(self, df: pd.DataFrame) -> bool:
        """(п. 4, 5) Проверяет, подходит ли DataFrame для графика"""
        if df.empty or len(df.columns) != 2:
            return False

        if df.iloc[:, 1].isnull().any():
            logger.warning("Данные для графика содержат NaN/None, пропускаем.")
            return False

        if is_numeric_dtype(df.iloc[:, 1]):
            return True
        return False

    def _detect_chart_type(self, df: pd.DataFrame, prompt: str) -> str:
        """(п. 4, 5) Определяет тип графика"""
        prompt_lower = prompt.lower();
        if "динамика" in prompt_lower: return "line"
        if "доли" in prompt_lower: return "pie"
        if not df.empty and len(df.columns) > 0:
            first_col_name = str(df.columns[0]).lower()
            if 'date' in first_col_name: return "line"
        return "bar"

    def generate_plotly_json(self, df: pd.DataFrame, prompt: str) -> str | None:
        """
        (п. 5) Главный метод. Генерирует "красивый" JSON для Plotly.
        """
        try:
            if not self._is_plottable(df):
                logger.info("Данные не подходят для построения графика (is_plottable = False)")
                return None

            chart_type = self._detect_chart_type(df, prompt)
            x_col, y_col = df.columns[0], df.columns[1]

            labels = {
                x_col: x_col.replace('_', ' ').title(),
                y_col: y_col.replace('_', ' ').title()
            }

            if chart_type == 'line':
                fig = px.line(df, x=x_col, y=y_col, title=prompt, markers=True, labels=labels,
                              hover_data={y_col: ':.2f'})
            elif chart_type == 'pie':
                fig = px.pie(df, names=x_col, values=y_col, title=prompt, labels=labels)
                fig.update_traces(textposition='inside', textinfo='percent+label')
            else:  # 'bar'
                fig = px.bar(df, x=x_col, y=y_col, title=prompt, labels=labels, hover_data={y_col: ':.2f'})

            fig.update_layout(template="plotly_white", title_x=0.5)
            logger.info(f"График '{chart_type}' успешно сгенерирован.")
            return fig.to_json()

        except Exception as e:
            logger.error(f"Ошибка при генерации графика Plotly: {e}", exc_info=True)
            return None  # График не критичен