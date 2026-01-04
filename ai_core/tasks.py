from celery import shared_task
from .services import run_vector_indexing
import logging

logger = logging.getLogger(__name__)

@shared_task
def task_reindex_vectors():
    """
    Фоновая задача для запуска индексации через Celery.
    """
    logger.info("Celery: Начало переиндексации векторов...")
    result = run_vector_indexing()
    return result