from __future__ import absolute_import, unicode_literals
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dasm.settings')

app = Celery('dasm')

# Читаем конфиг из settings.py по префиксу CELERY_
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
