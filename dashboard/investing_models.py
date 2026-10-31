"""Personal, exclusively virtual investment data."""
from decimal import Decimal
from django.conf import settings
from django.db import models
from .fields import ExactPriceField


def amount(default=Decimal('0')):
    return ExactPriceField(max_digits=38, decimal_places=12, default=default)


class PriceObservation(models.Model):
    share = models.ForeignKey('Share', on_delete=models.PROTECT, related_name='observations')
    price = amount()
    timestamp = models.DateTimeField()
    source = models.CharField(max_length=16)
    currency = models.CharField(max_length=20)

    class Meta:
        ordering = ['timestamp', 'pk']
        constraints = [models.UniqueConstraint(fields=['share', 'timestamp'], name='unique_share_observation')]


class WatchItem(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    share = models.ForeignKey('Share', on_delete=models.PROTECT)
    direction = models.CharField(max_length=2, choices=[('le', 'Цена ≤'), ('ge', 'Цена ≥')], default='le')
    target = amount()
    active = models.BooleanField(default=False)
    last_observation = models.ForeignKey(PriceObservation, null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['owner', 'share'], name='unique_owner_watch')]


class Notification(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    watch = models.ForeignKey(WatchItem, on_delete=models.CASCADE)
    observation = models.ForeignKey(PriceObservation, on_delete=models.PROTECT)
    message = models.CharField(max_length=255)
    read = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['watch', 'observation'], name='unique_watch_event')]


class Portfolio(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    currency = models.CharField(max_length=20)

    def __str__(self):
        return self.name


class Position(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='positions')
    share = models.ForeignKey('Share', on_delete=models.PROTECT)
    quantity = amount()
    average_price = amount()
    realized = amount()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['portfolio', 'share'], name='unique_portfolio_position')]


class Trade(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='trades')
    share = models.ForeignKey('Share', on_delete=models.PROTECT)
    side = models.CharField(max_length=4, choices=[('buy', 'Покупка'), ('sell', 'Продажа')])
    quantity = amount()
    price = amount()
    currency = models.CharField(max_length=20)
    realized = amount()
    created_at = models.DateTimeField(auto_now_add=True)
    strategy = models.ForeignKey('Strategy', null=True, blank=True, on_delete=models.PROTECT)
    observation = models.ForeignKey(PriceObservation, null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        ordering = ['-pk']
        constraints = [models.UniqueConstraint(fields=['strategy', 'observation'], name='unique_strategy_trade')]


class Strategy(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    portfolio = models.OneToOneField(Portfolio, on_delete=models.CASCADE)
    share = models.ForeignKey('Share', on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    buy_below = amount()
    sell_above = amount()
    quantity = amount()
    initial_capital = amount()
    cash = amount()
    enabled = models.BooleanField(default=True)
    # Creation watermark: do not trade historical observations.
    created_at = models.DateTimeField(auto_now_add=True)
    last_observation = models.ForeignKey(PriceObservation, null=True, blank=True, on_delete=models.PROTECT)


class StrategyEvent(models.Model):
    strategy = models.ForeignKey(Strategy, on_delete=models.CASCADE, related_name='events')
    observation = models.ForeignKey(PriceObservation, on_delete=models.PROTECT)
    message = models.CharField(max_length=255)

    class Meta:
        ordering = ['-pk']
        constraints = [models.UniqueConstraint(fields=['strategy', 'observation'], name='unique_strategy_event')]
