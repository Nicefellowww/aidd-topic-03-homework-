from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from dashboard.models import Share
from dashboard.services.investing import record_quote, process_rules


class Command(BaseCommand):
    help = 'Save an explicitly synthetic demo quote for a DEMO instrument and process rules (no Redis).'

    def add_arguments(self, parser):
        parser.add_argument('ticker')
        parser.add_argument('price')

    def handle(self, *args, **options):
        if settings.MARKET_DATA_PROVIDER != 'demo':
            raise CommandError('Команда доступна только при MARKET_DATA_PROVIDER=demo.')
        try:
            share = Share.objects.get(ticker=options['ticker'], figi__startswith='DEMO-')
            event, _ = record_quote(share.pk, Decimal(options['price']), timezone.now(), 'demo')
        except (Share.DoesNotExist, InvalidOperation, ValidationError) as exc:
            raise CommandError(f'Нужна DEMO-акция и положительная цена: {exc}') from exc
        self.stdout.write(f'DEMO — synthetic quote #{event.pk}: {event.price} {event.currency}')
        self.stdout.write(str(process_rules()))
