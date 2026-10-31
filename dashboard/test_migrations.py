from decimal import Decimal
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class UpgradeTests(TransactionTestCase):
    def test_populated_legacy_database_upgrades_without_uid_collision(self):
        executor = MigrationExecutor(connection)
        old = [('dashboard', '0002_update_share')]
        final = [('dashboard', '0008_share_price_source_alter_share_last_price_and_more')]
        executor.migrate(old)
        try:
            Share = executor.loader.project_state(old).apps.get_model('dashboard', 'Share')
            for index in range(2):
                Share.objects.create(figi=f'OLD{index}', ticker=f'OLD{index}',
                                     isin='legacy', name='Legacy', currency='rub')
            executor = MigrationExecutor(connection)
            executor.migrate([('dashboard', '0007_add_updated_at')])
            Share = executor.loader.project_state([('dashboard', '0007_add_updated_at')]).apps.get_model('dashboard', 'Share')
            Share.objects.update(last_price=123.75)
            executor = MigrationExecutor(connection)
            executor.migrate(final)
            Share = executor.loader.project_state(final).apps.get_model('dashboard', 'Share')
            items = list(Share.objects.all())
            self.assertEqual(len({item.uid for item in items}), 2)
            self.assertEqual(items[0].last_price, Decimal('123.75'))
            self.assertIsNone(items[0].updated_at)
        finally:
            MigrationExecutor(connection).migrate(final)
