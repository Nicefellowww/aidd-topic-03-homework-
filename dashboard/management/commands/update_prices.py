from django.core.management.base import BaseCommand
from dashboard.tasks import update_last_price


class Command(BaseCommand):
    help = 'Fetch quotes, persist history, check notifications and simulate strategies (no Redis).'

    def handle(self, *args, **options):
        self.stdout.write(f'Updated shares: {update_last_price.run()}')
