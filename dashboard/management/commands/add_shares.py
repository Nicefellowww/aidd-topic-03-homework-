from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from dashboard.models import Share
from dashboard.services.market_data import MarketDataError, get_provider


class Command(BaseCommand):
    help = 'Import catalogue from explicitly configured MARKET_DATA_SOURCE'

    def handle(self, *args, **options):
        try:
            items = get_provider().shares()
            with transaction.atomic():
                for item in items:
                    fields = dict(item)
                    figi = fields.pop('figi')
                    Share.objects.update_or_create(figi=figi, defaults=fields)
        except (MarketDataError, IntegrityError) as exc:
            raise CommandError('Import failed; catalogue unchanged. Check source/identifiers.') from exc
        self.stdout.write(self.style.SUCCESS(f'Imported {len(items)} instruments'))
