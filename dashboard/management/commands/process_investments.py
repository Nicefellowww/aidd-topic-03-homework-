from django.core.management.base import BaseCommand
from dashboard.tasks import process_investments


class Command(BaseCommand):
    help = 'Check personal rules against persisted quotes without fetching prices or using Redis.'

    def handle(self, *args, **options):
        self.stdout.write(str(process_investments.run()))
