from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from dashboard.models import Share
from dashboard.services.providers import (
    ProviderConfigurationError,
    get_provider,
)


class Command(BaseCommand):
    help = "Import the share catalogue from the configured market data provider"

    def add_arguments(self, parser):
        parser.add_argument(
            "--provider",
            choices=("demo", "tinkoff"),
            help="Override MARKET_DATA_PROVIDER for this run",
        )

    def handle(self, *args, **options):
        try:
            provider = get_provider(options.get("provider"))
            instruments = provider.list_shares()
        except ProviderConfigurationError as exc:
            raise CommandError(str(exc)) from exc

        if provider.is_demo:
            self.stdout.write(
                self.style.WARNING(
                    "DEMO source: importing synthetic shares, not real market data."
                )
            )

        created_count = 0
        updated_count = 0
        skipped_count = 0

        for instrument in instruments:
            try:
                with transaction.atomic():
                    _share, created = Share.objects.update_or_create(
                        figi=instrument.figi,
                        defaults={
                            "isin": instrument.isin,
                            "name": instrument.name,
                            "ticker": instrument.ticker,
                            "currency": instrument.currency,
                            "uid": instrument.uid,
                        },
                    )
            except IntegrityError as exc:
                skipped_count += 1
                self.stderr.write(
                    f"Skipped {instrument.ticker}: unique constraint conflict ({exc})"
                )
                continue

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported shares: created={created_count}, "
                f"updated={updated_count}, skipped={skipped_count}"
            )
        )
