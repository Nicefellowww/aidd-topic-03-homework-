from django.core.management.base import BaseCommand, CommandError
from dashboard.tasks import update_last_price


class Command(BaseCommand):
    help = 'Run the same price refresh synchronously (without Redis)'

    def handle(self, *args, **options):
        result = update_last_price()
        self.stdout.write(str(result))
        if result['failed']:
            raise CommandError('Some prices could not be refreshed')
