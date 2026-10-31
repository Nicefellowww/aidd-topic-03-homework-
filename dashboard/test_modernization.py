from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from dashboard.models import Share
from dashboard.services.market_data import quotation, DemoProvider, TBankProvider, MarketDataError, DEMO_SHARES
from dashboard.tasks import update_last_price


@override_settings(MARKET_DATA_SOURCE='demo')
class ModernizationTests(TestCase):
    def setUp(self):
        self.share = Share.objects.create(**DEMO_SHARES[0])
        self.user = get_user_model().objects.create_user('test@example.org', email='test@example.org', password='Long-test-Password19!')
        self.api = APIClient()

    def test_anonymous_reads_and_all_mutations_denied(self):
        self.assertEqual(self.api.get('/api/v1/shares/').status_code, 200)
        self.assertEqual(self.api.get(f'/api/v1/shares/{self.share.pk}/').status_code, 200)
        for method, url, data in [('post', '/api/v1/shares/', DEMO_SHARES[1]),
                                  ('put', f'/api/v1/shares/{self.share.pk}/', DEMO_SHARES[0]),
                                  ('patch', f'/api/v1/shares/{self.share.pk}/', {'name': 'Changed'}),
                                  ('delete', f'/api/v1/shares/{self.share.pk}/', {})]:
            self.assertEqual(getattr(self.api, method)(url, data, format='json').status_code, 403)
        for name in ['create', 'update', 'delete']:
            url = reverse('dashboard:'+name, args=[] if name == 'create' else [self.share.pk])
            self.assertEqual(self.client.post(url, DEMO_SHARES[1]).status_code, 302)
        self.assertEqual(Share.objects.count(), 1)

    def test_uid_required_unique_decimal_and_manual_source(self):
        self.api.force_authenticate(self.user)
        data = dict(DEMO_SHARES[1], last_price='123456789012345.123456789')
        self.assertEqual(self.api.post('/api/v1/shares/', data).status_code, 201)
        share = Share.objects.get(figi=data['figi'])
        self.assertEqual(share.last_price, Decimal(data['last_price']))
        self.assertEqual(share.price_source, 'manual')
        self.assertIsNone(share.updated_at)
        data = dict(DEMO_SHARES[2]); data.pop('uid')
        self.assertEqual(self.api.post('/api/v1/shares/', data).status_code, 400)
        data['uid'] = self.share.uid
        self.assertEqual(self.api.post('/api/v1/shares/', data).status_code, 400)
        self.assertEqual(self.api.patch(f'/api/v1/shares/{self.share.pk}/', {'last_price': '-0.1'}).status_code, 400)

    def test_filter_search_order_pagination(self):
        Share.objects.create(**DEMO_SHARES[1])
        for query in ['ticker=DEMO1', 'name=Демонстрационная компания 1', 'search=DEMO1']:
            self.assertEqual(self.api.get('/api/v1/shares/?'+query).json()['count'], 1)
        response = self.api.get('/api/v1/shares/?ordering=-ticker&limit=1').json()
        self.assertEqual(response['results'][0]['ticker'], 'DEMO2')
        self.assertIsNotNone(response['next'])

    def test_update_trend_timestamps_stale_and_failure_isolation(self):
        stamp = timezone.now()
        for price, trend in [('10.123456789', None), ('11.123456789', True),
                             ('11.123456789', None), ('9.000000001', False)]:
            stamp += timedelta(minutes=1)
            with patch('dashboard.tasks.get_last_data', return_value=(Decimal(price), stamp)):
                self.assertEqual(update_last_price()['updated'], 1)
            self.share.refresh_from_db()
            self.assertEqual(self.share.last_price, Decimal(price))
            self.assertEqual(self.share.is_trend_high, trend)
            self.assertEqual(self.share.updated_at, stamp)
        with patch('dashboard.tasks.get_last_data', return_value=(Decimal('1'), stamp-timedelta(days=1))):
            self.assertEqual(update_last_price()['skipped'], 1)
        self.share.refresh_from_db()
        self.assertEqual(self.share.last_price, Decimal('9.000000001'))
        second = Share.objects.create(**DEMO_SHARES[1])
        with patch('dashboard.tasks.get_last_data', side_effect=[MarketDataError('offline'), (Decimal('7.25'), stamp)]):
            result = update_last_price()
        self.assertEqual(result, {'updated': 1, 'skipped': 0, 'failed': 1})
        second.refresh_from_db(); self.assertEqual(second.last_price, Decimal('7.25'))

    def test_import_is_idempotent_updates_metadata_and_preserves_price(self):
        update_last_price()
        self.share.refresh_from_db()
        self.share.name = 'Old name'; self.share.save()
        for _ in range(2):
            call_command('add_shares', stdout=StringIO())
        self.assertEqual(Share.objects.count(), 3)
        self.share.refresh_from_db()
        self.assertEqual(self.share.name, DEMO_SHARES[0]['name'])
        self.assertEqual(self.share.last_price, Decimal('100.123456789'))
        self.assertEqual(self.share.price_source, 'demo')

    def test_detail_missing_offline_and_demo_label(self):
        response = self.client.get(reverse('dashboard:detail', args=[self.share.pk]))
        self.assertContains(response, 'ДЕМОНСТРАЦИОННЫЕ')
        self.assertContains(response, 'Plotly.newPlot')
        self.assertEqual(self.client.get('/999999').status_code, 404)
        with patch('dashboard.services.graph.get_provider') as factory:
            factory.return_value.candles.side_effect = MarketDataError('offline')
            self.assertContains(self.client.get(f'/{self.share.pk}'), 'График недоступен')

    def test_html_crud_authenticated(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post('/create', DEMO_SHARES[1]).status_code, 302)
        share = Share.objects.get(ticker='DEMO2')
        self.assertEqual(self.client.post(f'/update/{share.pk}', dict(DEMO_SHARES[1], name='Changed')).status_code, 302)
        share.refresh_from_db(); self.assertEqual(share.name, 'Changed')
        self.assertEqual(self.client.get(f'/delete/{share.pk}').status_code, 200)
        self.assertTrue(Share.objects.filter(pk=share.pk).exists())
        self.assertEqual(self.client.post(f'/delete/{share.pk}').status_code, 302)
        self.assertFalse(Share.objects.filter(pk=share.pk).exists())

    def test_registration_invalid_weak_duplicate_case_login_logout(self):
        url = reverse('user:registration')
        for data in [{}, {'email': 'bad'}, {'email': 'new@example.org', 'password1': '123', 'password2': '123'},
                     {'email': 'new@example.org', 'password1': 'Good-Password21!', 'password2': 'different'}]:
            self.assertEqual(self.client.post(url, data).status_code, 200)
        self.assertEqual(get_user_model().objects.count(), 1)
        data = {'email': 'NEW@Example.org', 'password1': 'Long-Secret-Password21!', 'password2': 'Long-Secret-Password21!'}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertTrue(get_user_model().objects.filter(username='new@example.org').exists())
        self.assertEqual(self.client.get(reverse('user:logout')).status_code, 405)
        self.assertEqual(self.client.post(reverse('user:logout')).status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.post(url, data).status_code, 200)
        self.assertEqual(self.client.post(reverse('user:auth'), {}).status_code, 200)
        self.assertEqual(self.client.post(reverse('user:auth'), {'email': data['email'], 'password': data['password1']}).status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_csrf_enforced_for_html_and_session_api(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post('/create', DEMO_SHARES[1]).status_code, 403)
        self.assertEqual(client.post('/api/v1/shares/', DEMO_SHARES[1]).status_code, 403)
        self.assertEqual(client.post(reverse('user:logout')).status_code, 403)

    def test_admin_staff_only(self):
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        self.user.is_staff = True; self.user.is_superuser = True; self.user.save()
        self.assertEqual(self.client.get('/admin/dashboard/share/').status_code, 200)

    def test_real_provider_contract_and_decimal_conversion(self):
        self.assertEqual(quotation({'units': '10', 'nano': 123456789}), Decimal('10.123456789'))
        self.assertEqual(quotation({'units': '-1', 'nano': -500000000}), Decimal('-1.5'))
        self.share.figi = 'REAL'; self.share.uid = 'real-uid'
        provider = TBankProvider()
        with patch.object(provider, 'request', return_value={'lastPrices': [
                {'price': {'units': '12', 'nano': 500000001}, 'time': '2026-01-15T12:00:00Z'}]}) as request:
            price, stamp = provider.price(self.share)
            self.assertEqual(price, Decimal('12.500000001'))
            self.assertIsNotNone(stamp.tzinfo)
            request.assert_called_once_with('MarketDataService', 'GetLastPrices', {'instrumentId': ['real-uid']})
        with override_settings(TINKOFF_TOKEN=''):
            with self.assertRaises(MarketDataError): provider.shares()
        with self.assertRaises(MarketDataError): DemoProvider().price(self.share)

    def test_schedule_default(self):
        from config.celery import app
        self.assertEqual(app.conf.beat_schedule['update-prices']['schedule'], 300)
