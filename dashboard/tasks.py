import logging
from django.conf import settings
from config.celery import app
from dashboard.models import Share
from dashboard.services.market_data import get_last_data

logger = logging.getLogger('main')


@app.task
def update_last_price():
    result = {'updated': 0, 'skipped': 0, 'failed': 0}
    for share in Share.objects.iterator():
        try:
            price, stamp = get_last_data(share)
            if not price.is_finite() or price < 0:
                raise ValueError('Invalid price')
            from dashboard.services.investing import record_price
            if record_price(share, price, stamp, settings.MARKET_DATA_SOURCE):
                result['updated'] += 1
            else:
                result['skipped'] += 1
        except Exception:
            logger.warning('Price update failed for share %s', share.pk, exc_info=True)
            result['failed'] += 1
    process_investing()
    return result


@app.task
def process_investing():
    from dashboard.services.investing import process_pending
    process_pending()
