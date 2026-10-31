from django.conf import settings

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

    Each provider event is persisted atomically with the current price.
    The shared service uses save() so auto_now updates the successful-fetch time;
    duplicate provider events do not create additional history rows.
    """

    from dashboard.services.investing import record_quote, process_rules

    updated = 0
    for share in Share.objects.all().iterator():
        try:
            [last_price, quote_time] = get_last_data(share)
            record_quote(share.pk, last_price, quote_time, settings.MARKET_DATA_PROVIDER)
            updated += 1
        except Exception:
            logger.exception("Unable to update price for share id %s", share.id)

    logger.info("Price update finished, updated %s shares", updated)
    process_rules()
    return updated


@app.task
def process_investments():
    """Retry alert/strategy processing independently of quote fetching."""
    from dashboard.services.investing import process_rules
    return process_rules()
