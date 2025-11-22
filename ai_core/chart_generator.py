import pandas as pd
import plotly.express as px
import logging
from pandas.api.types import is_numeric_dtype
import textwrap  # (НОВЫЙ ИМПОРТ)

logger = logging.getLogger(__name__)


class ChartGenerator:
    """
    Отвечает за логику графиков.
    ВЕРСИЯ 2.1: Улучшенный layout + перенос строк в заголовке.
    """

    def _is_plottable(self, df: pd.DataFrame) -> bool:
        if df.empty or len(df.columns) != 2:
            return False
        if df.iloc[:, 1].isnull().any():
            return False
        if is_numeric_dtype(df.iloc[:, 1]):
            return True
        return False

    def _detect_chart_type(self, df: pd.DataFrame, prompt: str) -> str:
        prompt_lower = prompt.lower();
        if "динамика" in prompt_lower: return "line"
        if "доли" in prompt_lower: return "pie"
        if not df.empty and len(df.columns) > 0:
            first_col_name = str(df.columns[0]).lower()
            if 'date' in first_col_name: return "line"
        return "bar"

    def generate_plotly_json(self, df: pd.DataFrame, prompt: str) -> str | None:
        try:
            if not self._is_plottable(df):
                return None

            chart_type = self._detect_chart_type(df, prompt)
            x_col, y_col = df.columns[0], df.columns[1]

            labels = {
                x_col: x_col.replace('_', ' ').title(),
                y_col: y_col.replace('_', ' ').title()
            }

            # (НОВОЕ) Разбиваем длинный заголовок на строки
            wrapped_title = "<br>".join(textwrap.wrap(prompt, width=50))

            if chart_type == 'line':
                fig = px.line(df, x=x_col, y=y_col, title=wrapped_title, markers=True, labels=labels,
                              hover_data={y_col: ':.2f'})
            elif chart_type == 'pie':
                fig = px.pie(df, names=x_col, values=y_col, title=wrapped_title, labels=labels)
                fig.update_traces(textposition='inside', textinfo='percent+label')
            else:  # 'bar'
                fig = px.bar(df, x=x_col, y=y_col, title=wrapped_title, labels=labels, hover_data={y_col: ':.2f'},
                             text_auto='.2s')

            fig.update_layout(
                template="plotly_white",
                title_x=0.5,
                autosize=True,
                margin=dict(l=20, r=20, t=80, b=20),  # (ИЗМЕНЕНО) Увеличили верхний отступ (t=80) для заголовка
                xaxis=dict(automargin=True, tickangle=-45 if chart_type == 'bar' else 0),
                yaxis=dict(automargin=True),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )

            return fig.to_json()

        except Exception as e:
            logger.error(f"Ошибка при генерации графика Plotly: {e}", exc_info=True)
            return None