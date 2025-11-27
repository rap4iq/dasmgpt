import pandas as pd
import plotly.express as px
import logging
from pandas.api.types import is_numeric_dtype, is_datetime64_any_dtype
import textwrap

logger = logging.getLogger(__name__)


class ChartGenerator:
    def _is_plottable(self, df: pd.DataFrame) -> bool:
        # 1. Должно быть минимум 2 колонки (X и Y)
        if df.empty or len(df.columns) < 2:
            return False

        # 2. Вторая колонка должна быть числовой
        if df.iloc[:, 1].isnull().all():
            return False

        if is_numeric_dtype(df.iloc[:, 1]):
            return True

        return False

    def _detect_chart_type(self, df: pd.DataFrame, prompt: str) -> str:
        prompt_lower = prompt.lower()

        # 1. Ключевые слова
        line_keywords = ['динамика', 'тренд', 'хронология', 'по времени', 'trend', 'dynamic']
        pie_keywords = ['доля', 'доли', 'процент', 'структура', 'состав', 'pie', 'share', 'percentage']
        bar_keywords = ['сравнени', 'рейтинг', 'топ', 'bar', 'compare']

        if any(k in prompt_lower for k in line_keywords): return 'line'
        if any(k in prompt_lower for k in pie_keywords): return 'pie'
        if any(k in prompt_lower for k in bar_keywords): return 'bar'

        # 2. Анализ данных
        first_col = df.iloc[:, 0]
        first_col_name = df.columns[0].lower()

        is_date = False
        if is_datetime64_any_dtype(first_col):
            is_date = True
        elif any(x in first_col_name for x in ['date', 'year', 'month', 'day']):
            is_date = True
        else:
            try:
                pd.to_datetime(first_col.head(5), errors='raise')
                is_date = True
            except:
                pass

        if is_date: return 'line'

        return 'bar'

    def generate_plotly_json(self, df: pd.DataFrame, prompt: str) -> str | None:
        try:
            if not self._is_plottable(df):
                logger.info("Данные не подходят для графика.")
                return None

            chart_type = self._detect_chart_type(df, prompt)
            x_col, y_col = df.columns[0], df.columns[1]


            # Если это категории (Bar/Pie) и их слишком много (>20),
            # мы берем только Топ-20, чтобы график был читаемым.
            if chart_type in ['bar', 'pie'] and len(df) > 20:
                logger.info(f"Слишком много категорий ({len(df)}). Берем Топ-20.")
                df = df.sort_values(by=y_col, ascending=False).head(20)
                prompt += " (Топ-20)"

            labels = {
                x_col: x_col.replace('_', ' ').title(),
                y_col: y_col.replace('_', ' ').title()
            }

            wrapped_title = "<br>".join(textwrap.wrap(prompt, width=60))
            fig = None

            if chart_type == 'line':
                fig = px.line(
                    df, x=x_col, y=y_col,
                    title=wrapped_title, markers=True, labels=labels
                )
                fig.update_traces(fill='tozeroy', line=dict(width=3))

            elif chart_type == 'pie':
                fig = px.pie(
                    df, names=x_col, values=y_col,
                    title=wrapped_title, labels=labels,
                    hole=0.4
                )
                fig.update_traces(textposition='inside', textinfo='percent+label')

            else:  # 'bar'
                # Для Топ-20 всегда лучше горизонтальный бар (рейтинг)
                # Если данных мало (<5), можно вертикальный, но горизонтальный универсальнее для текста
                orientation = 'h' if len(df) > 10 else 'v'
                x_axis, y_axis = (y_col, x_col) if orientation == 'h' else (x_col, y_col)

                fig = px.bar(
                    df, x=x_axis, y=y_axis,
                    title=wrapped_title,
                    labels=labels,
                    text_auto='.2s',
                    orientation=orientation,
                    color=x_col if orientation == 'v' else y_col  # Раскраска
                )

                if orientation == 'h':
                    # Сортировка для горизонтального бара (самый большой сверху)
                    fig.update_layout(yaxis={'categoryorder': 'total ascending'})
                else:
                    fig.update_layout(showlegend=False)

            fig.update_layout(
                template="plotly_white",
                title_x=0.5,
                autosize=True,
                margin=dict(l=20, r=20, t=80, b=20),
                font=dict(family="Inter, sans-serif", size=12, color="#333"),
                xaxis=dict(automargin=True),
                yaxis=dict(automargin=True),
                paper_bgcolor='white',
                plot_bgcolor='white',
            )

            return fig.to_json()

        except Exception as e:
            logger.error(f"Ошибка при генерации графика Plotly: {e}", exc_info=True)
            return None