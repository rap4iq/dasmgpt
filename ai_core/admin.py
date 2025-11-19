from django.contrib import admin, messages
from .models import DataSource, SchemaTable, SchemaColumn
from .services import sync_database_schema

class SchemaColumnInline(admin.TabularInline):
    """
    (НОВОЕ) Позволяет админу "включать/выключать"
    и "описывать" колонки прямо в Таблице.
    """
    model = SchemaColumn
    # Показываем только НУЖНЫЕ поля
    fields = ('column_name', 'data_type', 'is_enabled', 'description_ru', 'is_metric', 'is_dimension')
    readonly_fields = ('data_type',) # Тип данных нельзя редактировать
    extra = 0 # Не показывать пустые формы


@admin.register(SchemaTable)
class SchemaTableAdmin(admin.ModelAdmin):
    """
    (НОВОЕ) Админка для "Курируемых Таблиц".
    Это "сердце" нашего Семантического слоя (п. 1 и 3).
    """
    list_display = ('table_name', 'data_source', 'is_enabled')
    list_filter = ('data_source', 'is_enabled')
    search_fields = ('table_name', 'description_ru')
    # (НОВОЕ) Встраиваем Колонки (Уровень 2) внутрь Таблиц (Уровень 1)
    inlines = [SchemaColumnInline]


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    """
    (Из вашего кода)
    Админка для Источников Данных.
    """
    list_display = ('name', 'engine', 'host', 'db_name', 'last_inspected', 'is_active')
    readonly_fields = ('last_inspected',)
    actions = ['run_schema_sync'] # (Из вашего кода)

    @admin.action(description='Запустить интроспекцию (Загрузить/Обновить схему)')
    def run_schema_sync(self, request, queryset):
        success_count = 0
        for datasource in queryset:
            is_success, error_msg = sync_database_schema(datasource)  # (Из вашего кода)
            if is_success:
                success_count += 1
            else:
                messages.error(request, f"Ошибка синхронизации {datasource.name}: {error_msg}")

        if success_count > 0:
            messages.success(request, f"Успешно синхронизировано {success_count} источников.")