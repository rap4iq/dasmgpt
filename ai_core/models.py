from django.db import models
from encrypted_fields.fields import EncryptedTextField
from pgvector.django import VectorField


class DataSource(models.Model):

    DB_TYPES = [
        ('django.db.backends.postgresql', 'PostgreSQL'),
        ('django.db.backends.mysql', 'MySQL'),
        ('django.db.backends.sqlite3', 'SQLite'),
    ]

    name = models.CharField(max_length=255, help_text="Напр., 'Основная DWH'")
    engine = models.CharField(max_length=255, choices=DB_TYPES, default='django.db.backends.postgresql')

    host = models.CharField(max_length=255, default='localhost')
    port = models.PositiveIntegerField(default=5432)
    db_name = models.CharField("Имя БД", max_length=255)
    db_user = models.CharField("Логин (read-only)", max_length=255)

    db_password = EncryptedTextField(help_text="Пароль будет зашифрован")

    is_active = models.BooleanField(default=True, help_text="Используется ли этот источник?")
    last_inspected = models.DateTimeField("Последняя инспекция", blank=True, null=True, editable=False)

    def __str__(self):
        return f"{self.name} ({self.db_user}@{self.host})"

    class Meta:
        verbose_name = "1. Источник данных"
        verbose_name_plural = "1. Источники данных"


class SchemaTable(models.Model):
    data_source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name="tables")
    table_name = models.CharField(max_length=255)

    description_ru = models.TextField(
        "Бизнес-описание (для ИИ)", blank=True, null=True,
        help_text="Напр.: 'Фактические расходы на ТВ, Радио, OOH...'"
    )

    # (НОВОЕ ПОЛЕ) Векторное представление описания
    # nomic-embed-text выдает векторы размером 768
    embedding = VectorField(dimensions=768, null=True, blank=True)

    is_enabled = models.BooleanField(default=False, help_text="Включить эту таблицу для ИИ?")

    def __str__(self):
        return self.table_name

    class Meta:
        verbose_name = "2. Курируемая Таблица"
        verbose_name_plural = "2. Курируемые Таблицы"
        unique_together = ('data_source', 'table_name')


class SchemaColumn(models.Model):
    schema_table = models.ForeignKey(SchemaTable, on_delete=models.CASCADE, related_name="columns")
    column_name = models.CharField(max_length=255)
    data_type = models.CharField(max_length=100, editable=False)

    is_metric = models.BooleanField("Метрика?", default=False, help_text="Это Метрика?")
    is_dimension = models.BooleanField("Измерение?", default=False, help_text="Это Измерение?")

    description_ru = models.TextField(
        "Бизнес-описание (для ИИ)", blank=True, null=True,
        help_text="Напр.: 'Фактические расходы в USD', 'Город (Астана, Алматы)'"
    )

    # (НОВОЕ ПОЛЕ)
    embedding = VectorField(dimensions=768, null=True, blank=True)

    is_enabled = models.BooleanField(default=True, help_text="Включить эту колонку для ИИ?")

    def __str__(self):
        return f"{self.schema_table.table_name}.{self.column_name}"

    class Meta:
        verbose_name = "3. Курируемый Столбец"
        verbose_name_plural = "3. Курируемые Столбцы"
        unique_together = ('schema_table', 'column_name')