from django.core.management.base import BaseCommand
from dashboard.services.investing import process_pending


class Command(BaseCommand):
    help = 'Обработать накопленные котировки: уведомления и виртуальные стратегии, без Redis.'

    def handle(self, *args, **options):
        process_pending()
        self.stdout.write('Уведомления и стратегии обработаны.')
