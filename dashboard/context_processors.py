from django.conf import settings


def market_data(request):
    """Expose the active market data source to templates.

    Demo prices are synthetic and must never be presented as real quotes.
    """

    provider = getattr(settings, "MARKET_DATA_PROVIDER", "demo")
    return {
        "market_data_provider": provider,
        "market_data_is_demo": provider == "demo",
    }
