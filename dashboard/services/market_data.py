"""Explicit demo fixtures and the official T-Invest REST transport."""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils.dateparse import parse_datetime


class MarketDataError(Exception):
    pass


def quotation(value):
    return Decimal(value['units']) + Decimal(value.get('nano', 0)) / Decimal(10**9)


DEMO_TIME = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
DEMO_SHARES = [dict(figi=f'DEMO{i:08}', uid=f'demo-{i}', isin=f'DEMO{i:08}',
                    ticker=f'DEMO{i}', name=f'Демонстрационная компания {i}', currency='rub')
               for i in range(1, 4)]


class DemoProvider:
    def shares(self):
        return [dict(item) for item in DEMO_SHARES]

    def price(self, share):
        try:
            index = next(i for i, item in enumerate(DEMO_SHARES, 1) if item['figi'] == share.figi)
        except StopIteration as exc:
            raise MarketDataError('Demo source only supports DEMO instruments') from exc
        return Decimal(index * 100) + Decimal('0.123456789'), DEMO_TIME

    def candles(self, share):
        price, _ = self.price(share)
        return [(DEMO_TIME - timedelta(days=179-i), price + Decimal(i-179) / 100)
                for i in range(180)]


class TBankProvider:
    BASE = 'https://invest-public-api.tbank.ru/rest/tinkoff.public.invest.api.contract.v1.'

    def request(self, service, method, body):
        if not settings.TINKOFF_TOKEN:
            raise MarketDataError('TINKOFF_TOKEN is required for tbank source')
        request = Request(self.BASE + service + '/' + method,
                          data=json.dumps(body).encode(), headers={
                              'Authorization': f'Bearer {settings.TINKOFF_TOKEN}',
                              'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=15) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            # Do not log request headers or credentials.
            raise MarketDataError(f'T-Invest {method} request failed') from exc

    def shares(self):
        items = self.request('InstrumentsService', 'Shares', {'instrumentStatus': 'INSTRUMENT_STATUS_BASE'})
        return [{key: item[key] for key in ('figi', 'uid', 'isin', 'ticker', 'name', 'currency')}
                for item in items['instruments']]

    def price(self, share):
        if share.figi.startswith('DEMO'):
            raise MarketDataError('Demo instrument cannot be requested from T-Invest')
        items = self.request('MarketDataService', 'GetLastPrices', {'instrumentId': [share.uid]})
        if not items.get('lastPrices'):
            raise MarketDataError('No last price returned')
        item = items['lastPrices'][0]
        stamp = parse_datetime(item['time'])
        if stamp is None or stamp.tzinfo is None:
            raise MarketDataError('Invalid quotation timestamp')
        return quotation(item['price']), stamp

    def candles(self, share):
        if share.figi.startswith('DEMO'):
            raise MarketDataError('Demo instrument cannot be requested from T-Invest')
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=180)
        items = self.request('MarketDataService', 'GetCandles', {
            'instrumentId': share.uid, 'from': start.isoformat(), 'to': end.isoformat(),
            'interval': 'CANDLE_INTERVAL_DAY'})
        return [(parse_datetime(item['time']), quotation(item['close']))
                for item in items.get('candles', [])]


def get_provider():
    return DemoProvider() if settings.MARKET_DATA_SOURCE == 'demo' else TBankProvider()


def get_last_data(share):
    return get_provider().price(share)
