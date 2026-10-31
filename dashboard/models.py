import uuid

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

    @property
    def price_display(self):
        if self.last_price is None:
            return "—"
        return format(self.last_price.normalize(), "f")
