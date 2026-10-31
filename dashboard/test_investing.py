from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, Client, override_settings
from django.utils import timezone
from dashboard.models import (Share, WatchItem, Notification, Portfolio, Position, Trade,
                              Strategy, StrategyEvent, PriceObservation)
from dashboard.services.investing import (record_price, process_pending, execute_trade,
                                          portfolio_summary, positive)
from dashboard.investing_forms import StrategyForm
from dashboard.services.market_data import DEMO_SHARES
from dashboard.tasks import update_last_price, process_investing


@override_settings(MARKET_DATA_SOURCE='demo')
class InvestingTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user('owner')
        self.other = get_user_model().objects.create_user('other')
        self.share = Share.objects.create(**DEMO_SHARES[0])
        self.portfolio = Portfolio.objects.create(owner=self.owner, name='Private fund', currency='rub')
        self.stamp = timezone.now()
        self.client.force_login(self.owner)

    def quote(self, price):
        self.stamp += timedelta(seconds=1)
        record_price(self.share, Decimal(price), self.stamp, 'demo')
        process_pending()

    def strategy(self, **kwargs):
        defaults = dict(owner=self.owner, portfolio=self.portfolio, share=self.share,
                        name='Private strategy', buy_below=100, sell_above=120,
                        quantity=2, initial_capital=1000, cash=1000)
        defaults.update(kwargs)
        return Strategy.objects.create(**defaults)

    def test_weighted_average_partial_sale_and_close(self):
        execute_trade(self.portfolio, self.share, 'buy', '2', '100')
        execute_trade(self.portfolio, self.share, 'buy', '3', '120')
        position = Position.objects.get()
        self.assertEqual(position.quantity, 5)
        self.assertEqual(position.average_price, 112)
        trade = execute_trade(self.portfolio, self.share, 'sell', '2', '130')
        self.assertEqual(trade.realized, 36)
        self.quote('125')
        summary = portfolio_summary(self.portfolio)
        self.assertEqual((summary['value'], summary['unrealized'], summary['realized']), (375, 39, 36))
        execute_trade(self.portfolio, self.share, 'sell', '3', '110')
        position.refresh_from_db()
        self.assertEqual((position.quantity, position.average_price, position.realized), (0, 0, 30))
        execute_trade(self.portfolio, self.share, 'buy', '1', '80')
        position.refresh_from_db()
        self.assertEqual((position.average_price, position.realized), (80, 30))

    def test_fractional_decimal_exact_storage(self):
        execute_trade(self.portfolio, self.share, 'buy', '0.123456789', '10.000000001')
        execute_trade(self.portfolio, self.share, 'sell', '0.000000001', '11.000000001')
        p = Position.objects.get()
        self.assertEqual(p.quantity, Decimal('0.123456788'))
        self.assertEqual(p.average_price, Decimal('10.000000001'))
        self.assertEqual(p.realized, Decimal('0.000000001'))

    def test_invalid_numbers_and_side(self):
        for number in ('0', '-1', 'NaN', 'Infinity', 'abc', '1e18', '0.0000000001'):
            with self.subTest(number=number), self.assertRaises(ValidationError):
                positive(number)
        for kwargs in [dict(side='oops', quantity=1, price=2), dict(side='buy', quantity=-1, price=2),
                       dict(side='buy', quantity=1, price=0)]:
            with self.assertRaises(ValidationError):
                execute_trade(self.portfolio, self.share, **kwargs)
        self.assertFalse(Trade.objects.exists())

    def test_oversell_atomic_and_currency_rejected(self):
        execute_trade(self.portfolio, self.share, 'buy', 2, 10)
        with self.assertRaises(ValidationError):
            execute_trade(self.portfolio, self.share, 'sell', 3, 20)
        self.assertEqual(Position.objects.get().quantity, 2)
        self.assertEqual(Trade.objects.count(), 1)
        self.share.currency = 'usd'; self.share.save()
        with self.assertRaises(ValidationError):
            execute_trade(self.portfolio, self.share, 'buy', 1, 20)
        self.assertIsNone(portfolio_summary(self.portfolio)['value'])

    def test_missing_price_does_not_become_zero(self):
        execute_trade(self.portfolio, self.share, 'buy', 1, 10)
        self.assertIsNone(portfolio_summary(self.portfolio)['unrealized'])

    def test_trade_overflow_rolls_back_position(self):
        with self.assertRaises(ValidationError):
            execute_trade(self.portfolio, self.share, 'buy', '999999999999999999', '999999999999999999')
        self.assertFalse(Position.objects.exists())
        self.assertFalse(Trade.objects.exists())

    def test_watch_crossing_rearm_and_replay(self):
        watch = WatchItem.objects.create(owner=self.owner, share=self.share, direction='le', target=100)
        for price in ('100', '99', '101', '100'):
            self.quote(price)
            process_pending()
        self.assertEqual(Notification.objects.count(), 2)
        watch.refresh_from_db(); self.assertTrue(watch.active)
        self.assertEqual(Notification.objects.first().owner, self.owner)

    def test_watch_above_and_edit_watermark(self):
        self.quote('120')
        response = self.client.post('/watches/', {'share': self.share.pk, 'direction': 'ge', 'target': '110'})
        self.assertEqual(response.status_code, 302)
        process_pending()
        self.assertEqual(Notification.objects.count(), 0)
        self.quote('121'); self.quote('122')
        self.assertEqual(Notification.objects.count(), 1)
        self.client.post('/watches/', {'share': self.share.pk, 'direction': 'le', 'target': '100'})
        self.assertEqual(WatchItem.objects.count(), 1)
        self.quote('100')
        self.assertEqual(Notification.objects.count(), 2)

    def test_history_dedup_stale_and_source(self):
        self.quote('100.123456789')
        self.assertFalse(record_price(self.share, Decimal('99'), self.stamp, 'demo'))
        self.assertFalse(record_price(self.share, Decimal('99'), self.stamp-timedelta(seconds=1), 'demo'))
        self.assertEqual(PriceObservation.objects.count(), 1)
        obs = PriceObservation.objects.get()
        self.assertEqual((obs.price, obs.source, obs.currency), (Decimal('100.123456789'), 'demo', 'rub'))
        self.share.refresh_from_db(); self.assertEqual(self.share.last_price, obs.price)

    def test_update_task_saves_history_and_processes_watch(self):
        WatchItem.objects.create(owner=self.owner, share=self.share, direction='ge', target=100)
        with patch('dashboard.tasks.get_last_data', return_value=(Decimal('101'), self.stamp)):
            update_last_price(); update_last_price()
        self.assertEqual(PriceObservation.objects.count(), 1)
        self.assertEqual(Notification.objects.count(), 1)

    def test_history_period_change_graph_and_empty(self):
        self.quote('100'); self.quote('125')
        response = self.client.get(f'/history/{self.share.pk}/')
        self.assertEqual(response.context['change'], 25)
        self.assertEqual(response.context['percent'], 25)
        self.assertContains(response, 'Plotly.newPlot')
        self.assertContains(response, '"height":440')
        self.assertContains(self.client.get(f'/history/{self.share.pk}/?start=2000-01-01&end=2000-01-02'), 'сохранённых котировок нет')
        response = self.client.get(f'/history/{self.share.pk}/?start=bad')
        self.assertTrue(response.context['period_form'].errors)
        response = self.client.get(f'/history/{self.share.pk}/?start=2030-01-01&end=2000-01-01')
        self.assertTrue(response.context['period_form'].errors)

    def test_history_zero_and_currency_change(self):
        self.quote('0'); self.quote('10')
        response = self.client.get(f'/history/{self.share.pk}/')
        self.assertIsNone(response.context['percent'])
        self.share.currency = 'usd'; self.share.save(); self.quote('20')
        self.assertIsNone(self.client.get(f'/history/{self.share.pk}/').context['change'])

    def test_strategy_buy_sell_profit_and_replay(self):
        strategy = self.strategy()
        self.quote('100'); self.quote('90')
        process_investing()
        self.assertEqual(Trade.objects.count(), 1)
        strategy.refresh_from_db(); self.assertEqual(strategy.cash, 800)
        self.quote('125'); process_pending()
        strategy.refresh_from_db()
        self.assertEqual(strategy.cash, 1050)
        self.assertEqual(Trade.objects.count(), 2)
        self.assertEqual(StrategyEvent.objects.count(), 3)
        response = self.client.get(f'/strategies/{strategy.pk}/')
        self.assertEqual(response.context['profit'], 50)
        self.assertEqual(response.context['percent'], 5)
        self.quote('100')
        self.assertEqual(Trade.objects.count(), 3)

    def test_strategy_insufficient_cash_disabled_and_zero_price(self):
        strategy = self.strategy(initial_capital=100, cash=100)
        self.quote('100')
        self.assertIn('недостаточно', StrategyEvent.objects.get().message)
        self.assertFalse(Trade.objects.exists())
        strategy.enabled = False; strategy.save()
        self.quote('20')
        strategy.refresh_from_db()
        strategy.enabled = True; strategy.save(update_fields=['enabled'])
        process_pending()
        self.assertFalse(Trade.objects.exists())
        self.quote('0')
        self.assertFalse(Trade.objects.exists())
        self.quote('20')
        self.assertEqual(Trade.objects.count(), 1)

    def test_strategy_skips_precreation_history(self):
        old = timezone.now()-timedelta(days=1)
        record_price(self.share, Decimal('80'), old, 'demo')
        self.strategy()
        process_pending()
        self.assertFalse(Trade.objects.exists())
        self.assertFalse(StrategyEvent.objects.exists())

    def test_strategy_transaction_rolls_back_failed_trade(self):
        strategy = self.strategy()
        self.stamp += timedelta(seconds=1)
        record_price(self.share, Decimal('90'), self.stamp, 'demo')
        with patch('dashboard.services.investing.execute_trade', side_effect=ValidationError('fail')):
            with self.assertRaises(ValidationError):
                process_pending()
        strategy.refresh_from_db()
        self.assertEqual(strategy.cash, 1000)
        self.assertIsNone(strategy.last_observation_id)
        self.assertFalse(StrategyEvent.objects.exists())
        process_pending(); self.assertEqual(Trade.objects.count(), 1)

    def test_strategy_forms_rules_and_managed_portfolio(self):
        data = dict(name='Rules', share=self.share.pk, buy_below='100', sell_above='90', quantity='2', initial_capital='1000', enabled='on')
        self.assertFalse(StrategyForm(data).is_valid())
        data['sell_above'] = '120'
        response = self.client.post('/strategies/', data)
        self.assertEqual(response.status_code, 302)
        item = Strategy.objects.get()
        self.assertEqual(item.portfolio.owner, self.owner)
        self.assertEqual(item.cash, 1000)
        self.quote('100')
        response = self.client.post(f'/strategies/{item.pk}/', dict(name='Updated', buy_below='95', sell_above='130', enabled='on', cash='999999'))
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db(); self.assertEqual(item.cash, 800)
        self.assertEqual(item.buy_below, 95)
        with self.assertRaises(ValidationError):
            execute_trade(item.portfolio, self.share, 'buy', 1, 10)
        self.assertEqual(self.client.post(f'/portfolios/{item.portfolio.pk}/', {}).status_code, 403)

    def test_owner_isolation_all_lists_and_direct_mutations(self):
        watch = WatchItem.objects.create(owner=self.owner, share=self.share, target=100)
        self.quote('90')
        notification = Notification.objects.get()
        strategy = self.strategy()
        self.client.force_login(self.other)
        for url, secret in [('/portfolios/', 'Private fund'), ('/strategies/', 'Private strategy'), ('/watches/', notification.message)]:
            self.assertNotContains(self.client.get(url), secret)
        for url in (f'/portfolios/{self.portfolio.pk}/', f'/strategies/{strategy.pk}/'):
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post(url, {}).status_code, 404)
        for url in (f'/watches/{watch.pk}/delete/', f'/notifications/{notification.pk}/read/'):
            self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(WatchItem.objects.filter(pk=watch.pk).exists())
        notification.refresh_from_db(); self.assertFalse(notification.read)

    def test_anonymous_private_pages_and_csrf(self):
        self.client.logout()
        for url in ('/watches/', '/portfolios/', '/strategies/', f'/portfolios/{self.portfolio.pk}/'):
            self.assertEqual(self.client.get(url).status_code, 302)
        client = Client(enforce_csrf_checks=True); client.force_login(self.owner)
        for url in ('/watches/', '/portfolios/', '/strategies/'):
            self.assertEqual(client.post(url, {}).status_code, 403)

    def test_html_trade_validation_notification_read_and_delete(self):
        data = dict(share=self.share.pk, side='buy', quantity='2', price='100')
        self.assertEqual(self.client.post(f'/portfolios/{self.portfolio.pk}/', data).status_code, 302)
        data.update(side='sell', quantity='3')
        self.assertContains(self.client.post(f'/portfolios/{self.portfolio.pk}/', data), 'сверх позиции')
        WatchItem.objects.create(owner=self.owner, share=self.share, target=100)
        self.quote('90')
        notification = Notification.objects.get()
        self.client.post(f'/notifications/{notification.pk}/read/')
        notification.refresh_from_db(); self.assertTrue(notification.read)
        self.assertEqual(self.client.get(f'/watches/{notification.watch_id}/delete/').status_code, 405)
        self.client.post(f'/watches/{notification.watch_id}/delete/')
        self.assertFalse(WatchItem.objects.exists())

    def test_management_commands_same_logic_and_duplicate_protection(self):
        self.strategy()
        stamp = (timezone.now()+timedelta(minutes=1)).isoformat()
        for _ in range(2):
            call_command('demo_price', 'DEMO1', '90', at=stamp, stdout=StringIO())
            call_command('process_investing', stdout=StringIO())
        self.assertEqual(Trade.objects.count(), 1)
        self.assertEqual(PriceObservation.objects.count(), 1)

    def test_protected_share_deletion_is_user_error(self):
        self.quote('100')
        self.assertContains(self.client.post(f'/delete/{self.share.pk}'), 'не может быть удалена')
        from rest_framework.test import APIClient
        api = APIClient(); api.force_authenticate(self.owner)
        self.assertEqual(api.delete(f'/api/v1/shares/{self.share.pk}/').status_code, 400)
        self.assertTrue(Share.objects.filter(pk=self.share.pk).exists())

    def test_provider_duplicate_after_manual_edit_stays_ignored(self):
        self.quote('100')
        self.share.refresh_from_db()
        self.share.last_price = Decimal('110'); self.share.save()
        self.assertFalse(record_price(self.share, Decimal('99'), self.stamp, 'demo'))
        self.share.refresh_from_db()
        self.assertEqual(self.share.last_price, 110)
        self.assertEqual(PriceObservation.objects.count(), 1)

    def test_postgres_style_trailing_zero_decimals(self):
        execute_trade(self.portfolio, self.share, 'buy', Decimal('2.000000000000'), Decimal('100.000000000000'))
        self.assertEqual(Position.objects.get().quantity, 2)
