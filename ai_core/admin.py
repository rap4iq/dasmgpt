from django.contrib import admin, messages
from django.conf import settings
import ollama
from .models import DataSource, SchemaTable, SchemaColumn
from .services import sync_database_schema
from .tasks import task_reindex_vectors

# ==========================================
# 🧠 ЭВРИСТИКА (Правила для авто-выбора колонок)
# ==========================================
# Колонки, которые мы ТОЧНО хотим видеть
INTERESTING_KEYWORDS = [
    'name', 'title', 'status', 'type', 'category', 'city', 'region', 'country',  # Текст
    'date', 'year', 'month', 'day', 'time',  # Даты
    'price', 'cost', 'budget', 'amount', 'total', 'sum', 'revenue', 'profit',  # Деньги
    'count', 'qty', 'quantity', 'rate', 'score', 'percent', 'ratio',  # Числа
    'user', 'client', 'manager', 'agent', 'owner'  # Люди
]

# Колонки, которые мы ТОЧНО НЕ хотим (мусор)
JUNK_KEYWORDS = [
    'token', 'secret', 'password', 'hash', 'slug',
    'created_at', 'updated_at', 'modified', 'version',
    'lft', 'rght', 'tree_id', 'level',
    'is_staff', 'is_superuser', 'last_login'
]


def is_column_interesting(col_name):
    """Определяет, полезна ли колонка для аналитики."""
    col_name = col_name.lower()
    if col_name == 'id': return False
    if any(k in col_name for k in JUNK_KEYWORDS): return False
    if any(k in col_name for k in INTERESTING_KEYWORDS): return True
    return False


def generate_ai_desc_safe(prompt_text, model_name):
    """Безопасный вызов AI"""
    try:
        client = ollama.Client(host=settings.OLLAMA_HOST)
        response = client.generate(model=model_name, prompt=prompt_text, options={'temperature': 0.5})
        return response['response'].strip().replace('"', '').replace("'", "")
    except:
        return None


# ==========================================
# 📋 INLINE И ТАБЛИЦЫ
# ==========================================
class SchemaColumnInline(admin.TabularInline):
    model = SchemaColumn
    fields = ('column_name', 'data_type', 'is_enabled', 'description_ru')
    readonly_fields = ('data_type',)
    extra = 0
    can_delete = False


@admin.register(SchemaTable)
class SchemaTableAdmin(admin.ModelAdmin):
    list_display = ('table_name', 'data_source', 'is_enabled', 'short_desc', 'columns_count')
    list_filter = ('data_source', 'is_enabled')
    search_fields = ('table_name', 'description_ru')
    inlines = [SchemaColumnInline]
    actions = ['enable_tables', 'disable_tables', 'auto_curate_table']

    def short_desc(self, obj):
        return obj.description_ru[:50] + "..." if obj.description_ru else "-"

    short_desc.short_description = "Описание"

    def columns_count(self, obj):
        return obj.columns.count()

    columns_count.short_description = "Колонок"

    # --- ACTION 1: Массовое включение ---
    @admin.action(description="✅ Включить выбранные таблицы")
    def enable_tables(self, request, queryset):
        rows = queryset.update(is_enabled=True)
        messages.success(request, f"Включено таблиц: {rows}")

    @admin.action(description="❌ Выключить выбранные таблицы")
    def disable_tables(self, request, queryset):
        rows = queryset.update(is_enabled=False)
        messages.success(request, f"Выключено таблиц: {rows}")

    # --- ACTION 2: 🚀 ПОЛНАЯ АВТОМАТИЗАЦИЯ ---
    @admin.action(description="🚀 AI: Полная авто-настройка (Описание + Колонки)")
    def auto_curate_table(self, request, queryset):
        for table in queryset:
            # 1. Включаем таблицу
            table.is_enabled = True

            # 2. Описание таблицы (если нет)
            if not table.description_ru:
                prompt = f"Опиши одной фразой на русском, какие данные хранит таблица '{table.table_name}' в базе аналитики."
                desc = generate_ai_desc_safe(prompt, settings.OLLAMA_SUMMARY_MODEL)
                if desc: table.description_ru = desc

            table.save()

            # 3. Работа с колонками (Фильтр 100+ столбцов)
            columns = table.columns.all()
            enabled_count = 0

            for col in columns:
                is_useful = is_column_interesting(col.column_name)
                col.is_enabled = is_useful

                if is_useful:
                    enabled_count += 1
                    name = col.column_name.lower()
                    dtype = col.data_type.upper()

                    is_num = any(t in dtype for t in ['INT', 'DECIMAL', 'FLOAT', 'NUMERIC'])
                    if is_num and any(x in name for x in ['budget', 'cost', 'price', 'amount', 'sum', 'count', 'cnt']):
                        col.is_metric = True
                    else:
                        col.is_dimension = True

                    if not col.description_ru:
                        prompt_col = f"Переведи название колонки '{col.column_name}' (таблица {table.table_name}) на русский бизнес-язык, с синонимами (минимум 2)."
                        desc_col = generate_ai_desc_safe(prompt_col, settings.OLLAMA_SUMMARY_MODEL)
                        if desc_col: col.description_ru = desc_col

                col.save()

            messages.success(request,
                             f"Таблица {table.table_name}: Обработано, включено {enabled_count} из {columns.count()} колонок.")


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'engine', 'host', 'db_name', 'last_inspected', 'is_active')
    actions = ['run_schema_sync', 'run_vectorization_bg']  # Оба действия здесь

    @admin.action(description='Запустить интроспекцию (Загрузить схему)')
    def run_schema_sync(self, request, queryset):
        success_count = 0
        for datasource in queryset:
            is_success, error_msg = sync_database_schema(datasource)
            if is_success:
                success_count += 1
            else:
                messages.error(request, f"Ошибка {datasource.name}: {error_msg}")
        if success_count > 0:
            messages.success(request, f"Синхронизировано {success_count} источников.")

    @admin.action(description='🧠 Запустить Векторизацию (Фоновая задача)')
    def run_vectorization_bg(self, request, queryset):
        # Запускаем Celery задачу
        task_reindex_vectors.delay()

        # Мгновенно сообщаем админу
        self.message_user(request,
                          "Задача векторизации запущена в фоне! Процесс займет несколько минут. Проверьте логи позже.",
                          level=messages.SUCCESS)