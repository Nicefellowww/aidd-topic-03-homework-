from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Load the explicitly labelled DEMO share catalogue "
        "(synthetic data, not real quotes)"
    )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.WARNING(
                "This command loads synthetic DEMO data only. "
                "It must not be used as real market quotes."
            )
        )
        call_command("add_shares", provider="demo")
