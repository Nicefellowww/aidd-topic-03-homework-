from django.utils import timezone

from config.celery import app
from config.settings import logger
from dashboard.models import Share
from dashboard.services.market_data import get_last_data


def calculate_trend(previous_price, current_price):
    """Return True for growth, False for decline, None for unknown/unchanged.

    ``None`` is used on the first successful update (no previous price) and when
    the price did not change, so the UI can show a neutral state.
    """

    if previous_price is None or current_price is None:
        return None
    if current_price > previous_price:
        return True
    if current_price < previous_price:
        return False
    return None


@app.task
def update_last_price():
    """Update the last price and trend flag for every share.

    ``updated_at`` is set explicitly because ``QuerySet.update()`` bypasses
    ``auto_now``; the field means "time of the last successful price update".
    """

    updated = 0
    for share in Share.objects.all().iterator():
        try:
            [last_price, _quote_time] = get_last_data(share)
            previous_price = share.last_price
            share.last_price = last_price
            share.is_trend_high = calculate_trend(previous_price, last_price)
            share.updated_at = timezone.now()
            share.save(
                update_fields=["last_price", "is_trend_high", "updated_at"]
            )
            updated += 1
        except Exception:
            logger.exception("Unable to update price for share id %s", share.id)

    logger.info("Price update finished, updated %s shares", updated)
    return updated
