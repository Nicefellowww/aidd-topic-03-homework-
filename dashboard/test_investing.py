from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from dashboard.models import (PriceHistory, WatchItem, Notification, Portfolio, Position,
                              Trade, Strategy, StrategyExecution)
from dashboard.services.investing import (record_quote, execute_trade, portfolio_summary,
    check_watch, run_strategy, strategy_summary, starting_cursor)
from dashboard.tasks import update_last_price
from dashboard.tests import create_share

User = get_user_model()
NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)


class InvestmentCase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner@example.com', password='A-long-test-pass-8')
        self.other = User.objects.create_user(username='other@example.com', password='A-long-test-pass-8')
        self.share = create_share(currency='usd')
        self.portfolio = Portfolio.objects.create(owner=self.owner, name='Private portfolio', currency='usd')

    def quote(self, price, day=0, source='demo'):
        return record_quote(self.share.pk, D(price), NOW + timedelta(days=day), source)[0]

    def watch(self, **kwargs):
        values = dict(owner=self.owner, share=self.share, target=D('100'), condition='above')
        values.update(kwargs)
        return WatchItem.objects.create(**values)

    def strategy(self, **kwargs):
        values = dict(owner=self.owner, name='Private strategy', share=self.share, currency='usd', source='demo',
                      initial_capital=D('1000'), cash=D('1000'), buy_below=D('95'), sell_above=D('105'), order_quantity=D('2'))
        values.update(kwargs)
        return Strategy.objects.create(**values)

    def trade(self, side, quantity, price):
        return execute_trade(self.owner, self.portfolio.pk, self.share, side, D(quantity), D(price))


class PortfolioTests(InvestmentCase):
    def test_weighted_average_partial_sale_and_pnl(self):
        self.trade('buy', '2', '10.123456789')
        self.trade('buy', '3', '20.123456789')
        position = Position.objects.get()
        self.assertEqual(position.quantity, D('5'))
        self.assertEqual(position.average_price, D('16.123456789'))
        self.trade('sell', '2', '25.123456789')
        position.refresh_from_db()
        self.assertEqual(position.quantity, D('3'))
        self.assertEqual(position.average_price, D('16.123456789'))
        self.assertEqual(position.realized_pnl, D('18'))
        self.quote('30.123456789')
        rows, totals = portfolio_summary(self.portfolio)
        self.assertEqual(totals['value'], D('90.370370367'))
        self.assertEqual(totals['unrealized'], D('42'))
        self.assertEqual(totals['pnl'], D('60'))
        self.trade('sell', '3', '30.123456789')
        position.refresh_from_db()
        self.assertEqual(position.quantity, 0)
        self.assertEqual(position.average_price, 0)
        self.assertEqual(position.realized_pnl, D('60'))

    def test_oversell_is_atomic(self):
        self.trade('buy', '2', '10')
        with self.assertRaises(ValidationError):
            self.trade('sell', '2.000001', '12')
        self.assertEqual(Position.objects.get().quantity, D('2'))
        self.assertEqual(Trade.objects.count(), 1)

    def test_sell_without_position_does_not_create_empty_row(self):
        with self.assertRaises(ValidationError):
            self.trade('sell', '1', '10')
        self.assertFalse(Position.objects.exists())

    def test_invalid_inputs_are_rejected(self):
        for side, quantity, price in [('buy', '0', '1'), ('sell', '-1', '1'), ('bad', '1', '1'),
                                      ('buy', '1', '-1'), ('buy', 'NaN', '1'), ('buy', '1', 'Infinity'),
                                      ('buy', '0.0000001', '1'), ('buy', '1', '0.0000000001'),
                                      ('buy', '0.000001', '0.000000001')]:
            with self.subTest(side=side, quantity=quantity, price=price), self.assertRaises(ValidationError):
                self.trade(side, quantity, price)
        self.assertFalse(Trade.objects.exists())

    def test_cross_currency_and_other_owner_are_rejected(self):
        self.portfolio.currency = 'rub'
        self.portfolio.save()
        with self.assertRaises(ValidationError):
            self.trade('buy', '1', '10')
        with self.assertRaises(Portfolio.DoesNotExist):
            execute_trade(self.other, self.portfolio.pk, self.share, 'buy', D('1'), D('10'))
        self.assertFalse(Trade.objects.exists())

    def test_trade_failure_rolls_back_position(self):
        self.trade('buy', '1', '10')
        with patch.object(Trade, 'save', side_effect=RuntimeError('storage failure')):
            with self.assertRaises(RuntimeError):
                self.trade('buy', '1', '20')
        self.assertEqual(Position.objects.get().quantity, D('1'))
        self.assertEqual(Trade.objects.count(), 1)

    def test_missing_quote_does_not_value_position_at_zero(self):
        self.share.last_price = None
        self.share.save()
        self.trade('buy', '1', '10')
        _, totals = portfolio_summary(self.portfolio)
        self.assertIsNone(totals['value'])
        self.assertIsNone(totals['pnl'])


class HistoryTests(InvestmentCase):
    def test_quote_retry_is_immutable_and_unique(self):
        first = self.quote('12.123456789')
        again = self.quote('99')
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(PriceHistory.objects.count(), 1)
        again.refresh_from_db()
        self.assertEqual(again.price, D('12.123456789'))
        self.share.refresh_from_db()
        self.assertEqual(self.share.last_price, D('12.123456789'))

    @patch('dashboard.tasks.get_last_data')
    def test_existing_update_task_saves_history_and_retries_rules(self, fetch):
        watch = self.watch()
        strategy = self.strategy(buy_below=D('110'), sell_above=D('120'))
        fetch.return_value = [D('100'), NOW]
        self.assertEqual(update_last_price.run(), 1)
        self.assertEqual(update_last_price.run(), 1)
        self.assertEqual(PriceHistory.objects.count(), 1)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(StrategyExecution.objects.count(), 1)
        strategy.refresh_from_db()
        self.assertEqual(strategy.quantity, D('2'))

    @patch('dashboard.tasks.get_last_data', side_effect=RuntimeError('no quote'))
    def test_failed_fetch_does_not_save_history(self, fetch):
        with self.assertLogs('main', level='ERROR'):
            self.assertEqual(update_last_price.run(), 0)
        self.assertFalse(PriceHistory.objects.exists())

    def test_late_quote_does_not_overwrite_current_price(self):
        self.quote('110', 2)
        self.quote('90', 0)
        self.share.refresh_from_db()
        self.assertEqual(self.share.last_price, D('110'))
        self.assertEqual(PriceHistory.objects.count(), 2)

    def test_invalid_price_or_naive_time_is_rejected(self):
        for price in ['0', '-1', 'NaN']:
            with self.assertRaises(ValidationError):
                self.quote(price)
        with self.assertRaises(ValidationError):
            record_quote(self.share.pk, D('1'), NOW.replace(tzinfo=None), 'demo')
        self.assertFalse(PriceHistory.objects.exists())

    @patch('dashboard.services.providers.get_provider', side_effect=AssertionError('No provider on stored history page'))
    def test_empty_history_never_falls_back_to_candles(self, provider):
        response = self.client.get(f'/history/{self.share.pk}/')
        self.assertContains(response, 'Нет сохранённых котировок')
        self.assertNotContains(response, 'plotly-graph-div')

    def test_period_stats_graph_and_source_separation(self):
        self.quote('100', 0)
        self.quote('150', 1)
        self.quote('300', 2)
        self.quote('999', 1, source='tinkoff')
        response = self.client.get(f'/history/{self.share.pk}/?source=demo&start=2026-10-31&end=2026-11-01')
        self.assertEqual(len(response.context['points']), 2)
        self.assertEqual(response.context['delta'], D('50'))
        self.assertEqual(response.context['percent'], D('50'))
        self.assertContains(response, 'plotly-graph-div')
        self.assertContains(response, 'синтетические')
        bad = self.client.get(f'/history/{self.share.pk}/?source=demo&start=2026-11-02&end=2026-10-31')
        self.assertContains(bad, 'Начало периода позже конца')

    def test_quote_unique_constraint(self):
        self.quote('10')
        with self.assertRaises(IntegrityError), transaction.atomic():
            PriceHistory.objects.create(share=self.share, price=D('20'), source='demo', currency='usd', quoted_at=NOW)


class MonitoringTests(InvestmentCase):
    def test_crossing_rearms_only_after_condition_becomes_false(self):
        watch = self.watch()
        for day, price in enumerate(['90', '100', '101', '99', '100']):
            self.quote(price, day)
            check_watch(watch.pk)
            check_watch(watch.pk)
        self.assertEqual(Notification.objects.count(), 2)
        self.assertTrue(all(n.owner_id == self.owner.pk for n in Notification.objects.all()))

    def test_below_condition_and_inactive_watch(self):
        watch = self.watch(condition='below', active=False)
        self.quote('100')
        self.assertEqual(check_watch(watch.pk), 0)
        watch.active = True
        watch.save()
        self.assertEqual(check_watch(watch.pk), 1)

    def test_source_filter_and_out_of_order_quote(self):
        watch = self.watch()
        self.quote('110', 2)
        self.assertEqual(check_watch(watch.pk), 1)
        self.quote('90', 0)
        check_watch(watch.pk)
        self.quote('110', 3)
        self.assertEqual(check_watch(watch.pk), 0)
        self.quote('90', 4, source='tinkoff')
        self.assertEqual(check_watch(watch.pk), 0)
        self.assertEqual(Notification.objects.count(), 1)

    def test_management_command_uses_same_logic_and_is_idempotent(self):
        self.watch()
        self.strategy(buy_below=D('110'), sell_above=D('120'))
        self.quote('100')
        out = StringIO()
        call_command('process_investments', stdout=out)
        call_command('process_investments', stdout=out)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(StrategyExecution.objects.count(), 1)


class StrategyTests(InvestmentCase):
    def test_buy_sell_equity_and_idempotency(self):
        strategy = self.strategy()
        self.quote('90')
        self.assertEqual(run_strategy(strategy.pk), 1)
        strategy.refresh_from_db()
        self.assertEqual(strategy.cash, D('820'))
        self.assertEqual(strategy.quantity, D('2'))
        self.assertEqual(run_strategy(strategy.pk), 0)
        self.quote('110', 1)
        self.assertEqual(run_strategy(strategy.pk), 1)
        self.assertEqual(run_strategy(strategy.pk), 0)
        strategy.refresh_from_db()
        self.assertEqual(strategy.cash, D('1040'))
        self.assertEqual(strategy.quantity, 0)
        summary = strategy_summary(strategy)
        self.assertEqual(summary['pnl'], D('40'))
        self.assertEqual(summary['percent'], D('4'))
        self.assertEqual(StrategyExecution.objects.count(), 2)

    def test_insufficient_cash_and_hold_do_not_create_trades(self):
        strategy = self.strategy(initial_capital=D('100'), cash=D('100'))
        self.quote('90')
        run_strategy(strategy.pk)
        strategy.refresh_from_db()
        self.assertEqual(strategy.cash, D('100'))
        self.assertEqual(strategy.executions.get().action, 'skip')
        self.quote('100', 1)
        run_strategy(strategy.pk)
        self.assertEqual(strategy.executions.first().action, 'hold')

    def test_no_pyramiding_and_no_shorting(self):
        strategy = self.strategy()
        for day, price in enumerate(['110', '90', '89', '110', '111']):
            self.quote(price, day)
        self.assertEqual(run_strategy(strategy.pk), 2)
        self.assertEqual(strategy.executions.filter(action='buy').count(), 1)
        self.assertEqual(strategy.executions.filter(action='sell').count(), 1)
        strategy.refresh_from_db()
        self.assertEqual(strategy.quantity, 0)

    def test_currency_and_late_quotes_are_skipped(self):
        strategy = self.strategy()
        self.quote('100', 2)
        run_strategy(strategy.pk)
        self.quote('90', 0)
        run_strategy(strategy.pk)
        self.assertEqual(strategy.executions.first().action, 'skip')
        self.share.currency = 'rub'
        self.share.save()
        self.quote('90', 3)
        run_strategy(strategy.pk)
        self.assertEqual(strategy.executions.first().action, 'skip')
        strategy.refresh_from_db()
        self.assertEqual(strategy.quantity, 0)

    def test_creation_cursor_avoids_backtesting_old_quotes(self):
        self.quote('90')
        event = self.quote('110', 1)
        strategy = self.strategy(last_history_id=starting_cursor(self.share, 'demo'))
        run_strategy(strategy.pk)
        self.assertEqual(strategy.executions.get().event_id, event.pk)
        self.assertEqual(strategy.executions.get().action, 'hold')

    def test_failure_rolls_back_cash_and_cursor(self):
        strategy = self.strategy()
        self.quote('90')
        with patch.object(StrategyExecution, 'save', side_effect=RuntimeError('storage failure')):
            with self.assertRaises(RuntimeError):
                run_strategy(strategy.pk)
        strategy.refresh_from_db()
        self.assertEqual(strategy.cash, D('1000'))
        self.assertEqual(strategy.last_history_id, 0)
        self.assertFalse(strategy.executions.exists())
        self.assertEqual(run_strategy(strategy.pk), 1)

    def test_pause_and_threshold_validation(self):
        strategy = self.strategy(active=False)
        self.quote('90')
        self.assertEqual(run_strategy(strategy.pk), 0)
        strategy.buy_below = D('110')
        with self.assertRaises(ValidationError):
            strategy.full_clean()


class InvestmentViewsTests(InvestmentCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)

    def test_browser_forms_create_watch_portfolio_trade_and_strategy(self):
        self.assertEqual(self.client.post('/watchlist/', {'share': self.share.pk, 'source': 'demo', 'condition': 'above', 'target': '100', 'active': 'on', 'owner': self.other.pk}).status_code, 302)
        self.assertEqual(WatchItem.objects.get().owner, self.owner)
        self.assertEqual(self.client.post('/portfolios/', {'name': 'Browser portfolio', 'currency': 'USD'}).status_code, 302)
        portfolio = Portfolio.objects.get(name='Browser portfolio')
        self.assertEqual(portfolio.currency, 'usd')
        self.assertEqual(self.client.post(f'/portfolios/{portfolio.pk}/', {'share': self.share.pk, 'side': 'buy', 'quantity': '2', 'price': '10'}).status_code, 302)
        self.assertEqual(portfolio.trades.count(), 1)
        self.assertEqual(self.client.post('/strategies/', {'name': 'Browser strategy', 'share': self.share.pk, 'source': 'demo', 'initial_capital': '1000', 'buy_below': '95', 'sell_above': '105', 'order_quantity': '2', 'active': 'on'}).status_code, 302)
        strategy = Strategy.objects.get()
        self.assertEqual(strategy.cash, D('1000'))
        self.assertEqual(strategy.owner, self.owner)
        self.assertEqual(self.client.get(f'/strategies/{strategy.pk}/').status_code, 200)

    def test_direct_urls_cannot_read_or_mutate_another_owners_objects(self):
        watch = self.watch(owner=self.other)
        strategy = self.strategy(owner=self.other)
        portfolio = Portfolio.objects.create(owner=self.other, name='Other private portfolio', currency='usd')
        event = self.quote('100')
        note = Notification.objects.create(owner=self.other, watch=watch, event=event, message='Other private note')
        for url in [f'/watchlist/{watch.pk}/edit/', f'/watchlist/{watch.pk}/delete/', f'/watchlist/{watch.pk}/check/',
                    f'/portfolios/{portfolio.pk}/', f'/strategies/{strategy.pk}/', f'/strategies/{strategy.pk}/run/',
                    f'/notifications/{note.pk}/read/']:
            for method in ['get', 'post']:
                response = getattr(self.client, method)(url)
                self.assertIn(response.status_code, [404, 405], url)
        note.refresh_from_db()
        self.assertFalse(note.read)
        self.assertFalse(strategy.executions.exists())
        self.assertTrue(WatchItem.objects.filter(pk=watch.pk).exists())
        for url, secret in [('/portfolios/', 'Other private portfolio'), ('/strategies/', 'Private strategy'), ('/notifications/', 'Other private note')]:
            self.assertNotContains(self.client.get(url), secret)

    def test_anonymous_personal_urls_require_login(self):
        strategy = self.strategy()
        watch = self.watch()
        self.client.logout()
        for url in ['/watchlist/', '/notifications/', '/portfolios/', '/strategies/',
                    f'/portfolios/{self.portfolio.pk}/', f'/strategies/{strategy.pk}/', f'/watchlist/{watch.pk}/edit/']:
            self.assertEqual(self.client.get(url).status_code, 302)
            self.assertEqual(self.client.post(url).status_code, 302)

    def test_duplicate_watch_and_invalid_strategy_are_form_errors(self):
        self.watch()
        response = self.client.post('/watchlist/', {'share': self.share.pk, 'source': 'demo', 'condition': 'above', 'target': '100'})
        self.assertContains(response, 'уже в вашем списке')
        response = self.client.post('/strategies/', {'name': 'Bad', 'share': self.share.pk, 'source': 'demo', 'initial_capital': '100', 'buy_below': '110', 'sell_above': '105', 'order_quantity': '2'})
        self.assertContains(response, 'Порог покупки должен быть меньше')
        self.assertFalse(Strategy.objects.exists())

    def test_oversell_renders_error_and_post_only_actions(self):
        response = self.client.post(f'/portfolios/{self.portfolio.pk}/', {'share': self.share.pk, 'side': 'sell', 'quantity': '1', 'price': '10'})
        self.assertContains(response, 'Нельзя продать больше')
        watch = self.watch()
        for suffix in ['delete', 'check']:
            self.assertEqual(self.client.get(f'/watchlist/{watch.pk}/{suffix}/').status_code, 405)

    def test_owner_can_edit_watch_read_notification_and_pause_strategy(self):
        watch = self.watch()
        self.quote('100')
        self.assertEqual(self.client.post(f'/watchlist/{watch.pk}/check/').status_code, 302)
        note = Notification.objects.get()
        self.assertEqual(self.client.post(f'/notifications/{note.pk}/read/').status_code, 302)
        note.refresh_from_db()
        self.assertTrue(note.read)
        self.assertEqual(self.client.post(f'/watchlist/{watch.pk}/edit/', {'condition': 'below', 'target': '80', 'active': 'on'}).status_code, 302)
        watch.refresh_from_db()
        self.assertEqual(watch.target, D('80'))
        strategy = self.strategy()
        response = self.client.post(f'/strategies/{strategy.pk}/', {'name': 'Paused', 'buy_below': '95', 'sell_above': '105', 'order_quantity': '2'})
        self.assertEqual(response.status_code, 302)
        strategy.refresh_from_db()
        self.assertFalse(strategy.active)
        self.assertEqual(strategy.cash, D('1000'))

    def test_share_delete_preserves_financial_records_and_api_still_reads(self):
        self.quote('100')
        self.assertEqual(self.client.post(f'/delete/{self.share.pk}').status_code, 409)
        response = self.client.delete(f'/api/v1/shares/{self.share.pk}/')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get('/api/v1/shares/').status_code, 200)
        self.assertNotContains(self.client.get('/api/v1/shares/'), 'Private portfolio')


class AdditionalSafetyTests(InvestmentCase):
    def test_database_guards_notification_and_execution_replays(self):
        watch = self.watch()
        strategy = self.strategy(buy_below=D('110'), sell_above=D('120'))
        event = self.quote('100')
        check_watch(watch.pk)
        run_strategy(strategy.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Notification.objects.create(owner=self.owner, watch=watch, event=event, message='Duplicate')
        with self.assertRaises(IntegrityError), transaction.atomic():
            StrategyExecution.objects.create(strategy=strategy, event=event, action='buy', price=D('100'),
                                             quantity=D('2'), cash_after=D('600'), holdings_after=D('4'))
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(StrategyExecution.objects.count(), 1)

    def test_demo_quote_command_is_explicit_and_uses_shared_processing(self):
        self.share.figi = 'DEMO-TEST'
        self.share.save()
        self.watch()
        out = StringIO()
        call_command('record_demo_quote', self.share.ticker, '123.456789123', stdout=out)
        self.assertIn('DEMO — synthetic', out.getvalue())
        self.assertEqual(PriceHistory.objects.get().price, D('123.456789123'))
        self.assertEqual(Notification.objects.count(), 1)

    def test_demo_command_rejects_real_instrument_and_real_mode(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('record_demo_quote', self.share.ticker, '100')
        with override_settings(MARKET_DATA_PROVIDER='tinkoff'), self.assertRaises(CommandError):
            call_command('record_demo_quote', self.share.ticker, '100')
        self.assertFalse(PriceHistory.objects.exists())

    @patch('dashboard.tasks.get_last_data')
    def test_update_command_uses_existing_task_without_broker(self, fetch):
        fetch.return_value = [D('100'), NOW]
        call_command('update_prices', stdout=StringIO())
        self.assertEqual(PriceHistory.objects.count(), 1)

    def test_watch_edit_does_not_replay_old_event(self):
        watch = self.watch()
        self.quote('100')
        check_watch(watch.pk)
        self.client.force_login(self.owner)
        self.client.post(f'/watchlist/{watch.pk}/edit/', {'target': '90', 'condition': 'above', 'active': 'on'})
        self.assertEqual(check_watch(watch.pk), 0)
        self.assertEqual(Notification.objects.count(), 1)
        self.quote('100', 1)
        self.assertEqual(check_watch(watch.pk), 1)

    def test_csrf_is_required_for_personal_mutations(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        response = client.post('/portfolios/', {'name': 'No CSRF', 'currency': 'usd'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Portfolio.objects.filter(name='No CSRF').exists())
