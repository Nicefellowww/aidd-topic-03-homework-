from decimal import Decimal
from django.db import models


class ExactPriceField(models.DecimalField):
    """NUMERIC on PostgreSQL, decimal strings on SQLite (no REAL roundtrip)."""
    def get_internal_type(self):
        # Avoid SQLite's DecimalField float converter; use from_db_value below.
        return 'CharField'

    def db_type(self, connection):
        if connection.vendor == 'sqlite':
            return 'text'
        return f'numeric({self.max_digits}, {self.decimal_places})'

    def get_db_prep_value(self, value, connection, prepared=False):
        value = self.to_python(value)
        if value is None:
            return None
        return format(value, 'f') if connection.vendor == 'sqlite' else value

    def from_db_value(self, value, expression, connection):
        return None if value is None else Decimal(str(value))
