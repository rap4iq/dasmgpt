from django.db import migrations
from pgvector.django import HnswIndex

class Migration(migrations.Migration):
    dependencies = [
        ('ai_core', '0003_alter_schematable_is_enabled'),
    ]

    operations = [
        # Индекс для Таблиц
        migrations.AddIndex(
            model_name='schematable',
            index=HnswIndex(
                name='table_desc_index',
                fields=['embedding'],
                m=16,
                ef_construction=64,
                opclasses=['vector_cosine_ops']
            ),
        ),
        # Индекс для Колонок
        migrations.AddIndex(
            model_name='schemacolumn',
            index=HnswIndex(
                name='col_desc_index',
                fields=['embedding'],
                m=16,
                ef_construction=64,
                opclasses=['vector_cosine_ops']
            ),
        ),
    ]