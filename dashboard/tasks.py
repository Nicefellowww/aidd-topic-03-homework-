import logging
from django.conf import settings
from django.db import transaction
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
            with transaction.atomic():
                current = Share.objects.select_for_update().get(pk=share.pk)
                # Reject duplicate and late observations, including overlapping jobs.
                if current.updated_at and stamp <= current.updated_at:
                    result['skipped'] += 1
                    continue
                trend = None if current.last_price is None or current.last_price == price else price > current.last_price
                Share.objects.filter(pk=current.pk).update(
                    last_price=price, is_trend_high=trend, updated_at=stamp,
                    price_source=settings.MARKET_DATA_SOURCE)
                result['updated'] += 1
        except Exception:
            logger.warning('Price update failed for share %s', share.pk, exc_info=True)
            result['failed'] += 1
    return result
