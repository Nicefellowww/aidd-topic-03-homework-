"""Transactional business logic shared by Celery, commands and HTML forms."""
from decimal import Decimal, localcontext, InvalidOperation
from functools import wraps
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from dashboard.models import (Share, PriceObservation, WatchItem, Notification,
                              Portfolio, Position, Trade, Strategy, StrategyEvent)

def precise(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with localcontext() as ctx:
            ctx.prec = 60
            return function(*args, **kwargs)
    return wrapped


ZERO = Decimal('0')
SCALE = Decimal('0.000000000001')


def positive(value):
    try:
        value = Decimal(str(value))
        if not value.is_finite() or value <= 0 or value >= Decimal('1e18') or value.normalize().as_tuple().exponent < -9:
            raise ValueError
        return value
    except (ValueError, InvalidOperation):
        raise ValidationError('Требуется положительное конечное число < 10^18, до 9 знаков после точки.')


def rounded(value):
    return value.quantize(SCALE)


@precise
@transaction.atomic
def execute_trade(portfolio, share, side, quantity, price, *, strategy=None, observation=None):
    portfolio = Portfolio.objects.select_for_update().get(pk=portfolio.pk)
    if strategy is None and Strategy.objects.filter(portfolio=portfolio).exists():
        raise ValidationError('Портфель стратегии управляется только симулятором.')
    if side not in ('buy', 'sell'):
        raise ValidationError('Неизвестная операция.')
    quantity, price = positive(quantity), positive(price)
    if share.currency.lower() != portfolio.currency.lower():
        raise ValidationError('Валюта акции должна совпадать с валютой портфеля.')
    position, _ = Position.objects.get_or_create(portfolio=portfolio, share=share)
    if side == 'sell' and quantity > position.quantity:
        raise ValidationError('Продажа сверх позиции запрещена.')
    with localcontext() as ctx:
        ctx.prec = 60
        realized = ZERO
        if side == 'buy':
            new_quantity = position.quantity + quantity
            position.average_price = rounded((position.quantity * position.average_price + quantity * price) / new_quantity)
            position.quantity = new_quantity
        else:
            realized = rounded(quantity * (price - position.average_price))
            position.quantity -= quantity
            position.realized += realized
            if not position.quantity:
                position.average_price = ZERO
        for value in (position.quantity, position.average_price, position.realized, realized, quantity * price):
            if abs(value) >= Decimal('1e26'):
                raise ValidationError('Превышен предел размера операции/позиции.')
        position.save()
        return Trade.objects.create(portfolio=portfolio, share=share, side=side, quantity=quantity,
                                    price=price, currency=portfolio.currency, realized=realized,
                                    strategy=strategy, observation=observation)


def portfolio_summary(portfolio):
    rows, value, unrealized, realized = [], ZERO, ZERO, ZERO
    complete = True
    with localcontext() as ctx:
        ctx.prec = 60
        for position in portfolio.positions.select_related('share'):
            share = position.share
            marked = (share.last_price is not None and share.currency.lower() == portfolio.currency.lower())
            current = position.quantity * share.last_price if marked else None
            pnl = current - position.quantity * position.average_price if marked else None
            if position.quantity and not marked:
                complete = False
            if current is not None:
                value += current
                unrealized += pnl
            realized += position.realized
            rows.append(dict(position=position, value=current, unrealized=pnl))
    return dict(rows=rows, value=value if complete else None,
                unrealized=unrealized if complete else None, realized=realized)


@transaction.atomic
def process_watch(pk):
    watch = WatchItem.objects.select_for_update().select_related('share').get(pk=pk)
    observations = watch.share.observations.all()
    if watch.last_observation_id:
        observations = observations.filter(timestamp__gt=watch.last_observation.timestamp)
    for obs in observations:
        reached = obs.price <= watch.target if watch.direction == 'le' else obs.price >= watch.target
        if reached and not watch.active:
            Notification.objects.get_or_create(watch=watch, observation=obs, defaults={
                'owner': watch.owner, 'message': f'{watch.share.ticker}: {obs.price} {obs.currency}; цель {watch.direction} {watch.target}'})
        watch.active = reached
        watch.last_observation = obs
    watch.save()


@precise
@transaction.atomic
def process_strategy(pk):
    strategy = Strategy.objects.select_for_update().select_related('share', 'portfolio').get(pk=pk)
    observations = strategy.share.observations.filter(timestamp__gt=strategy.created_at)
    if strategy.last_observation_id:
        observations = observations.filter(timestamp__gt=strategy.last_observation.timestamp)
    for obs in observations:
        message = 'Условия сделки не выполнены.'
        if strategy.enabled:
            position = Position.objects.filter(portfolio=strategy.portfolio, share=strategy.share).first()
            held = position.quantity if position else ZERO
            side = 'sell' if held and obs.price >= strategy.sell_above else ('buy' if not held and obs.price <= strategy.buy_below else None)
            cost = strategy.quantity * obs.price
            if side and (obs.currency.lower() != strategy.portfolio.currency.lower()
                         or strategy.share.currency.lower() != strategy.portfolio.currency.lower()):
                message = 'Пропуск: валюта котировки изменилась.'
            elif side == 'buy' and strategy.cash < cost:
                message = 'Пропуск: недостаточно виртуальных средств.'
            elif side and obs.price > 0:
                trade = execute_trade(strategy.portfolio, strategy.share, side,
                                      strategy.quantity if side == 'buy' else held, obs.price,
                                      strategy=strategy, observation=obs)
                strategy.cash = rounded(strategy.cash + rounded(trade.quantity * obs.price) * (-1 if side == 'buy' else 1))
                message = f'{trade.get_side_display()}: {trade.quantity} × {obs.price} {obs.currency}'
        else:
            message = 'Стратегия выключена.'
        StrategyEvent.objects.get_or_create(strategy=strategy, observation=obs, defaults={'message': message})
        strategy.last_observation = obs
    strategy.save()


def process_pending():
    for pk in WatchItem.objects.values_list('pk', flat=True):
        process_watch(pk)
    for pk in Strategy.objects.values_list('pk', flat=True):
        process_strategy(pk)


@transaction.atomic
def record_price(share, price, stamp, source):
    price = Decimal(str(price))
    if not price.is_finite() or price < 0 or price >= Decimal('1e15') or price.normalize().as_tuple().exponent < -9:
        raise ValidationError('Некорректная котировка.')
    if stamp is None or timezone.is_naive(stamp):
        raise ValidationError('Необходимо время котировки с часовым поясом.')
    current = Share.objects.select_for_update().get(pk=share.pk)
    latest = current.observations.last()
    if (current.updated_at and stamp <= current.updated_at) or (latest and stamp <= latest.timestamp):
        return False
    trend = None if current.last_price is None or current.last_price == price else price > current.last_price
    Share.objects.filter(pk=current.pk).update(last_price=price, updated_at=stamp,
        is_trend_high=trend, price_source=source)
    PriceObservation.objects.get_or_create(share=current, timestamp=stamp, defaults={
        'price': price, 'source': source, 'currency': current.currency})
    return True
