from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal
from .fields import ExactPriceField


class Share(models.Model):
    """Акция"""

    figi = models.CharField(max_length=255, unique=True)
    isin = models.CharField(max_length=255)
    name = models.CharField(max_length=255, verbose_name="Наименование компании")
    ticker = models.CharField(max_length=10, unique=True, verbose_name="Тикер")
    currency = models.CharField(max_length=20, verbose_name="Валюта")
    uid = models.CharField(max_length=255, unique=True)
    last_price = ExactPriceField(max_digits=24, decimal_places=9, blank=True, null=True,
        validators=[MinValueValidator(Decimal("0"))], verbose_name="Текущая цена")
    is_trend_high = models.BooleanField(
        blank=True, null=True, verbose_name="Растет цена"
    )
    updated_at = models.DateTimeField(editable=False, blank=True, null=True)
    price_source = models.CharField(max_length=16, default="unknown", editable=False)

    def save(self, *args, **kwargs):
        old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if (old is None and self.last_price is not None) or (old and old.last_price != self.last_price):
            self.price_source = "manual"
            self.updated_at = None
            self.is_trend_high = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.ticker}: {self.name}"

    class Meta:
        verbose_name = "Акция"
        verbose_name_plural = "Акции"

# Imported here so Django discovers the models and migrations normally.
from .investing_models import (PriceObservation, WatchItem, Notification, Portfolio,
                               Position, Trade, Strategy, StrategyEvent)  # noqa: E402,F401
