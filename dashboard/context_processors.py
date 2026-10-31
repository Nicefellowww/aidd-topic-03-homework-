from django.conf import settings


def market_source(request):
    return {'market_data_source': settings.MARKET_DATA_SOURCE}
