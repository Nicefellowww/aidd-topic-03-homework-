import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


def generate_uid():
    """Generate a unique instrument identifier for manually created shares."""

    return uuid.uuid4().hex


class Share(models.Model):
    """Акция"""

    figi = models.CharField(max_length=255, unique=True)
    isin = models.CharField(max_length=255)
    name = models.CharField(max_length=255, verbose_name="Наименование компании")
    ticker = models.CharField(max_length=10, unique=True, verbose_name="Тикер")
    currency = models.CharField(max_length=20, verbose_name="Валюта")
    uid = models.CharField(
        max_length=255, unique=True, blank=True, default=generate_uid
    )
    last_price = models.DecimalField(
        max_digits=20,
        decimal_places=9,
        blank=True,
        null=True,
        verbose_name="Текущая цена",
    )
    is_trend_high = models.BooleanField(
        blank=True, null=True, verbose_name="Растет цена"
    )
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    class Meta:
        verbose_name = "Акция"
        verbose_name_plural = "Акции"

    def save(self, *args, **kwargs):
        if not self.uid:
            self.uid = generate_uid()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.ticker} — {self.name}"

    @property
    def price_display(self):
        if self.last_price is None:
            return "—"
        return format(self.last_price.normalize(), "f")


# Homework 4: personal data is always scoped through its owner in views/services.
POSITIVE = [MinValueValidator(Decimal('0.000000001')), MaxValueValidator(Decimal('1000000000'))]
QUANTITY = [MinValueValidator(Decimal('0.000001')), MaxValueValidator(Decimal('1000000'))]


class PriceHistory(models.Model):
    share = models.ForeignKey(Share, on_delete=models.PROTECT, related_name='prices')
    price = models.DecimalField(max_digits=28, decimal_places=9, validators=POSITIVE)
    quoted_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=16, choices=[('demo', 'Demo — синтетические'), ('tinkoff', 'Tinkoff')])
    currency = models.CharField(max_length=20)

    class Meta:
        ordering = ['quoted_at', 'id']
        constraints = [
            models.UniqueConstraint(fields=['share', 'source', 'quoted_at'], name='unique_quote_event'),
            models.CheckConstraint(condition=models.Q(price__gt=0), name='history_positive_price'),
        ]
        indexes = [models.Index(fields=['share', 'source', 'quoted_at'])]


class WatchItem(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    share = models.ForeignKey(Share, on_delete=models.PROTECT)
    condition = models.CharField(max_length=8, choices=[('above', 'Цена ≥ цели'), ('below', 'Цена ≤ цели')], default='above')
    target = models.DecimalField(max_digits=28, decimal_places=9, validators=POSITIVE)
    active = models.BooleanField(default=True)
    source = models.CharField(max_length=16, choices=PriceHistory._meta.get_field('source').choices, default='demo')
    matched = models.BooleanField(default=False)
    last_history_id = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['owner', 'share'], name='unique_owner_watch')]


class Notification(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    watch = models.ForeignKey(WatchItem, on_delete=models.SET_NULL, null=True)
    event = models.ForeignKey(PriceHistory, on_delete=models.PROTECT)
    message = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-id']
        constraints = [models.UniqueConstraint(fields=['watch', 'event'], name='unique_watch_notification')]


class Portfolio(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    currency = models.CharField(max_length=20)

    def __str__(self):
        return f'{self.name} ({self.currency})'


class Position(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='positions')
    share = models.ForeignKey(Share, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=24, decimal_places=6, default=0, validators=[MaxValueValidator(Decimal('1000000000'))])
    average_price = models.DecimalField(max_digits=28, decimal_places=9, default=0)
    realized_pnl = models.DecimalField(max_digits=28, decimal_places=9, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['portfolio', 'share'], name='unique_portfolio_position'),
            models.CheckConstraint(condition=models.Q(quantity__gte=0), name='position_nonnegative'),
        ]


class Trade(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='trades')
    share = models.ForeignKey(Share, on_delete=models.PROTECT)
    side = models.CharField(max_length=4, choices=[('buy', 'Покупка'), ('sell', 'Продажа')])
    quantity = models.DecimalField(max_digits=24, decimal_places=6, validators=QUANTITY)
    price = models.DecimalField(max_digits=28, decimal_places=9, validators=POSITIVE)
    realized_pnl = models.DecimalField(max_digits=28, decimal_places=9, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']


class Strategy(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    share = models.ForeignKey(Share, on_delete=models.PROTECT)
    currency = models.CharField(max_length=20)
    source = models.CharField(max_length=16, choices=PriceHistory._meta.get_field('source').choices)
    initial_capital = models.DecimalField(max_digits=28, decimal_places=9, validators=[MinValueValidator(Decimal('0.01')), MaxValueValidator(Decimal('1000000000000000'))])
    cash = models.DecimalField(max_digits=28, decimal_places=9)
    buy_below = models.DecimalField(max_digits=28, decimal_places=9, validators=POSITIVE)
    sell_above = models.DecimalField(max_digits=28, decimal_places=9, validators=POSITIVE)
    order_quantity = models.DecimalField(max_digits=24, decimal_places=6, validators=QUANTITY)
    quantity = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    active = models.BooleanField(default=True)
    last_history_id = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(cash__gte=0), name='strategy_nonnegative_cash'),
            models.CheckConstraint(condition=models.Q(quantity__gte=0), name='strategy_nonnegative_quantity'),
            models.CheckConstraint(condition=models.Q(buy_below__lt=models.F('sell_above')), name='strategy_threshold_order'),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.buy_below is not None and self.sell_above is not None and self.buy_below >= self.sell_above:
            raise ValidationError('Порог покупки должен быть меньше порога продажи.')


class StrategyExecution(models.Model):
    strategy = models.ForeignKey(Strategy, on_delete=models.CASCADE, related_name='executions')
    event = models.ForeignKey(PriceHistory, on_delete=models.PROTECT)
    action = models.CharField(max_length=8, choices=[('buy', 'Покупка'), ('sell', 'Продажа'), ('hold', 'Ожидание'), ('skip', 'Пропуск')])
    quantity = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    price = models.DecimalField(max_digits=28, decimal_places=9)
    cash_after = models.DecimalField(max_digits=28, decimal_places=9)
    holdings_after = models.DecimalField(max_digits=24, decimal_places=6)
    reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']
        constraints = [models.UniqueConstraint(fields=['strategy', 'event'], name='unique_strategy_event')]
