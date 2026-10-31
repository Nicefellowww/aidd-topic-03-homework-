"""Transactional business logic shared by HTTP, Celery and management commands."""
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from dashboard.models import (
    Share, PriceHistory, WatchItem, Notification, Portfolio, Position, Trade,
    Strategy, StrategyExecution,
)

ZERO = Decimal('0')
MONEY_STEP = Decimal('0.000000001')


def money(value):
    return value.quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def latest_event(share, source):
    return PriceHistory.objects.filter(share=share, source=source).order_by('-quoted_at', '-id').first()


def starting_cursor(share, source):
    # Evaluate the current quote once, never backtest all previously stored quotes.
    event = PriceHistory.objects.filter(share=share, source=source).order_by('-id').first()
    return event.id - 1 if event else 0


@transaction.atomic
def record_quote(share_id, price, quoted_at, source):
    """A provider timestamp identifies an immutable quote; retries reuse that row."""
    share = Share.objects.select_for_update().get(pk=share_id)
    if source not in {'demo', 'tinkoff'} or timezone.is_naive(quoted_at):
        raise ValidationError('Неверный источник или время котировки без часового пояса.')
    event = PriceHistory(share=share, price=price, quoted_at=quoted_at,
                         source=source, currency=share.currency.lower())
    event.full_clean(validate_unique=False, validate_constraints=False)
    event, created = PriceHistory.objects.get_or_create(
        share=share, source=source, quoted_at=quoted_at,
        defaults={'price': event.price, 'currency': event.currency},
    )
    newest = latest_event(share, source)
    if newest.pk == event.pk:
        from dashboard.tasks import calculate_trend
        share.is_trend_high = calculate_trend(share.last_price, event.price)
        share.last_price = event.price
        share.save(update_fields=['last_price', 'is_trend_high', 'updated_at'])
    return event, created


@transaction.atomic
def execute_trade(owner, portfolio_id, share, side, quantity, price):
    portfolio = Portfolio.objects.select_for_update().get(pk=portfolio_id, owner=owner)
    share = Share.objects.get(pk=share.pk)
    trade = Trade(portfolio=portfolio, share=share, side=side, quantity=quantity, price=price)
    trade.full_clean()
    quantity, price = trade.quantity, trade.price
    if money(quantity * price) <= ZERO:
        raise ValidationError('Стоимость сделки меньше точности учёта (0.000000001).')
    if share.currency.lower() != portfolio.currency:
        raise ValidationError('Валюта акции должна совпадать с валютой портфеля. Конвертации нет.')
    position, _ = Position.objects.get_or_create(portfolio=portfolio, share=share)
    if side == 'sell':
        if quantity > position.quantity:
            raise ValidationError('Нельзя продать больше имеющегося количества.')
        trade.realized_pnl = money((price - position.average_price) * quantity)
        position.realized_pnl += trade.realized_pnl
        position.quantity -= quantity
        if position.quantity == 0:
            position.average_price = ZERO
    else:
        total = position.quantity + quantity
        position.average_price = money((position.quantity * position.average_price + quantity * price) / total)
        position.quantity = total
    position.full_clean()
    position.save()
    trade.save()
    return trade


def portfolio_summary(portfolio):
    rows = []
    totals = {'cost': ZERO, 'value': ZERO, 'realized': ZERO, 'unrealized': ZERO}
    complete = True
    for position in portfolio.positions.select_related('share').order_by('share__ticker'):
        share = position.share
        current = share.last_price if share.currency.lower() == portfolio.currency else None
        cost = money(position.quantity * position.average_price)
        value = money(position.quantity * current) if current is not None else (ZERO if not position.quantity else None)
        pnl = value - cost if value is not None else None
        rows.append({'position': position, 'current': current, 'cost': cost, 'value': value, 'pnl': pnl})
        totals['cost'] += cost
        totals['realized'] += position.realized_pnl
        if value is None:
            complete = False
        else:
            totals['value'] += value
            totals['unrealized'] += pnl
    if not complete:
        totals['value'] = totals['unrealized'] = None
    totals['pnl'] = totals['realized'] + totals['unrealized'] if complete else None
    return rows, totals


@transaction.atomic
def check_watch(watch_id):
    watch = WatchItem.objects.select_for_update().select_related('share').get(pk=watch_id)
    if not watch.active:
        return 0
    count = 0
    previous = PriceHistory.objects.filter(share=watch.share, source=watch.source, id__lte=watch.last_history_id).order_by('-quoted_at', '-id').first()
    events = PriceHistory.objects.filter(share=watch.share, source=watch.source, id__gt=watch.last_history_id).order_by('id')
    for event in events:
        # Late/out-of-order quotes are stored but must not rewind live decisions.
        if previous and event.quoted_at < previous.quoted_at:
            watch.last_history_id = event.id
            continue
        matched = event.price >= watch.target if watch.condition == 'above' else event.price <= watch.target
        if matched and not watch.matched:
            _, created = Notification.objects.get_or_create(
                watch=watch, event=event,
                defaults={'owner': watch.owner, 'message':
                          f'{watch.share.ticker}: {event.price} {event.currency}; '
                          f'{watch.get_condition_display()} {watch.target}. Источник: {event.source}.'},
            )
            count += int(created)
        watch.matched = matched
        watch.last_history_id = event.id
        previous = event
    watch.save(update_fields=['matched', 'last_history_id'])
    return count


@transaction.atomic
def run_strategy(strategy_id):
    strategy = Strategy.objects.select_for_update().get(pk=strategy_id)
    if not strategy.active:
        return 0
    count = 0
    previous = PriceHistory.objects.filter(share=strategy.share, source=strategy.source, id__lte=strategy.last_history_id).order_by('-quoted_at', '-id').first()
    events = PriceHistory.objects.filter(share=strategy.share, source=strategy.source,
                                         id__gt=strategy.last_history_id).order_by('id')
    for event in events:
        action, quantity, reason = 'hold', ZERO, 'Условие сделки не выполнено.'
        if event.currency != strategy.currency:
            action, reason = 'skip', 'Валюта котировки не совпадает с валютой стратегии.'
        elif previous and event.quoted_at < previous.quoted_at:
            action, reason = 'skip', 'Запоздалая котировка.'
        elif strategy.quantity == 0 and event.price <= strategy.buy_below:
            cost = money(event.price * strategy.order_quantity)
            if cost <= ZERO:
                action, reason = 'skip', 'Стоимость покупки меньше точности учёта.'
            elif cost <= strategy.cash:
                action, quantity, reason = 'buy', strategy.order_quantity, ''
                strategy.cash -= cost
                strategy.quantity = quantity
            else:
                action, reason = 'skip', 'Недостаточно виртуальных средств; частичного исполнения нет.'
        elif strategy.quantity > 0 and event.price >= strategy.sell_above:
            action, quantity, reason = 'sell', strategy.quantity, ''
            strategy.cash += money(quantity * event.price)
            strategy.quantity = ZERO
        StrategyExecution.objects.create(
            strategy=strategy, event=event, action=action, quantity=quantity,
            price=event.price, cash_after=strategy.cash, holdings_after=strategy.quantity, reason=reason,
        )
        strategy.last_history_id = event.id
        if not previous or event.quoted_at >= previous.quoted_at:
            previous = event
        count += action in {'buy', 'sell'}
    strategy.full_clean()
    strategy.save(update_fields=['cash', 'quantity', 'last_history_id'])
    return count


def process_rules():
    """Per-object transactions: one invalid rule does not starve other users."""
    from config.settings import logger
    counts = {'notifications': 0, 'strategy_trades': 0}
    for model, handler, key in [(WatchItem, check_watch, 'notifications'), (Strategy, run_strategy, 'strategy_trades')]:
        for pk in model.objects.filter(active=True).values_list('pk', flat=True).iterator():
            try:
                counts[key] += handler(pk)
            except Exception:
                logger.exception('Unable to process %s id %s', model.__name__, pk)
    return counts


def strategy_summary(strategy):
    event = latest_event(strategy.share, strategy.source)
    price = event.price if event and event.currency == strategy.currency else None
    equity = money(strategy.cash + strategy.quantity * price) if price is not None else (strategy.cash if not strategy.quantity else None)
    pnl = equity - strategy.initial_capital if equity is not None else None
    percent = pnl / strategy.initial_capital * 100 if pnl is not None else None
    return {'price': price, 'equity': equity, 'pnl': pnl, 'percent': percent}
