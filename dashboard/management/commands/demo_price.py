from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from dashboard.models import Share
from dashboard.services.investing import record_price, process_pending


class Command(BaseCommand):
    help = 'Явно сохранить demo-котировку и обработать события (только DEMO-инструменты).'

    def add_arguments(self, parser):
        parser.add_argument('ticker')
        parser.add_argument('price')
        parser.add_argument('--at', help='ISO 8601 с часовым поясом, по умолчанию сейчас')

    def handle(self, ticker, price, at=None, **options):
        if settings.MARKET_DATA_SOURCE != 'demo':
            raise CommandError('Команда доступна только при MARKET_DATA_SOURCE=demo.')
        try:
            share = Share.objects.get(ticker=ticker, figi__startswith='DEMO')
            changed = record_price(share, Decimal(price), parse_datetime(at) if at else timezone.now(), 'demo')
            process_pending()
        except (Share.DoesNotExist, ValidationError, InvalidOperation, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write('Сохранено.' if changed else 'Повторная/старая котировка пропущена.')
