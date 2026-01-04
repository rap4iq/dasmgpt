from django.core.management.base import BaseCommand
from ai_core.services import run_vector_indexing

class Command(BaseCommand):
    help = 'Запускает индексацию (обертка над сервисом).'

    def handle(self, *args, **options):
        self.stdout.write("Запуск через сервис...")
        result = run_vector_indexing()
        self.stdout.write(self.style.SUCCESS(result))