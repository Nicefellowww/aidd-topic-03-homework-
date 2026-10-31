from config.settings import logger

from .providers import get_provider


def get_last_data(share):
    """Return ``[Decimal price, quote time]`` for a share.

    The provider is selected with ``MARKET_DATA_PROVIDER``.  The list shape is
    kept for compatibility with the original task implementation.
    """

    quote = get_provider().get_last_price(share)
    logger.info("Get last data for share with id %s", share.id)
    return [quote.price, quote.time]
