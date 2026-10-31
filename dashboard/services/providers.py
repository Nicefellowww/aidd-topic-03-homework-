"""Market data providers.

The application supports two explicitly separated sources:

* ``demo`` — deterministic synthetic data used for local checks without an
  external API token.  It is not a real quote feed.
* ``tinkoff`` — the real Tinkoff Invest API.  The optional SDK is imported
  lazily so that the demo mode does not require it.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Protocol

from django.conf import settings


class ProviderConfigurationError(RuntimeError):
    """Raised when the selected market data provider is not configured."""


@dataclass(frozen=True)
class Instrument:
    figi: str
    isin: str
    name: str
    ticker: str
    currency: str
    uid: str


@dataclass(frozen=True)
class PricePoint:
    price: Decimal
    time: datetime


@dataclass(frozen=True)
class Candle:
    time: datetime
    close: Decimal


class MarketDataProvider(Protocol):
    is_demo: bool

    def list_shares(self) -> list[Instrument]: ...

    def get_last_price(self, share) -> PricePoint: ...

    def get_candles(self, share, days: int = 180) -> list[Candle]: ...


def quotation_to_decimal(quotation) -> Decimal:
    """Convert a Tinkoff Quotation (units + nano) to an exact Decimal."""

    units = int(getattr(quotation, "units", 0) or 0)
    nano = int(getattr(quotation, "nano", 0) or 0)
    return Decimal(units) + (Decimal(nano) / Decimal(1_000_000_000))


class DemoMarketDataProvider:
    """Reproducible synthetic data source, never a real market feed."""

    is_demo = True

    _INSTRUMENTS = (
        Instrument(
            figi="DEMO-BBG-AAPL",
            isin="DEMO-US0378331005",
            name="Apple Inc. (демонстрационные данные)",
            ticker="DEMOAAPL",
            currency="usd",
            uid="demo-uid-aapl",
        ),
        Instrument(
            figi="DEMO-BBG-MSFT",
            isin="DEMO-US5949181045",
            name="Microsoft Corp. (демонстрационные данные)",
            ticker="DEMOMSFT",
            currency="usd",
            uid="demo-uid-msft",
        ),
        Instrument(
            figi="DEMO-BBG-SBER",
            isin="DEMO-RU0009029540",
            name="Сбербанк (демонстрационные данные)",
            ticker="DEMOSBER",
            currency="rub",
            uid="demo-uid-sber",
        ),
        Instrument(
            figi="DEMO-BBG-GAZP",
            isin="DEMO-RU0007661625",
            name="Газпром (демонстрационные данные)",
            ticker="DEMOGAZP",
            currency="rub",
            uid="demo-uid-gazp",
        ),
        Instrument(
            figi="DEMO-BBG-YNDX",
            isin="DEMO-NL0009803265",
            name="Яндекс (демонстрационные данные)",
            ticker="DEMOYNDX",
            currency="rub",
            uid="demo-uid-yndx",
        ),
    )

    _BASE_PRICES = {
        "DEMOAAPL": Decimal("189.50"),
        "DEMOMSFT": Decimal("415.20"),
        "DEMOSBER": Decimal("280.15"),
        "DEMOGAZP": Decimal("145.30"),
        "DEMOYNDX": Decimal("3900.75"),
    }

    def list_shares(self) -> list[Instrument]:
        return list(self._INSTRUMENTS)

    def _price_for(self, ticker: str, day: date) -> Decimal:
        base = self._BASE_PRICES.get(ticker, Decimal("100.00"))
        seed = int(hashlib.sha256(ticker.encode("utf-8")).hexdigest()[:8], 16)
        days_since_epoch = (day - date(2020, 1, 1)).days
        wave = Decimal(
            str(round(math.sin((days_since_epoch + seed % 360) / 18.0), 6))
        )
        trend = Decimal(days_since_epoch % 365) * Decimal("0.00005")
        price = base * (Decimal("1") + Decimal("0.05") * wave + trend)
        return price.quantize(Decimal("0.0001"))

    def get_last_price(self, share) -> PricePoint:
        today = date.today()
        return PricePoint(
            price=self._price_for(share.ticker, today),
            time=datetime.combine(today, time(12, 0), tzinfo=timezone.utc),
        )

    def get_candles(self, share, days: int = 180) -> list[Candle]:
        today = date.today()
        result = []
        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            result.append(
                Candle(
                    time=datetime.combine(day, time(12, 0), tzinfo=timezone.utc),
                    close=self._price_for(share.ticker, day),
                )
            )
        return result


class TinkoffMarketDataProvider:
    """Real Tinkoff Invest API integration (optional dependency)."""

    is_demo = False

    def __init__(self, token: str):
        if not token:
            raise ProviderConfigurationError(
                "TINKOFF_TOKEN is required when MARKET_DATA_PROVIDER=tinkoff"
            )
        self.token = token

    @staticmethod
    def _client():
        try:
            from tinkoff.invest import Client
        except ImportError as exc:  # pragma: no cover - depends on optional SDK
            raise ProviderConfigurationError(
                "The optional 'tinkoff-investments' package is not installed. "
                "Use MARKET_DATA_PROVIDER=demo or install requirements-tinkoff.txt."
            ) from exc
        return Client

    def list_shares(self) -> list[Instrument]:
        client_class = self._client()
        with client_class(self.token) as client:
            response = client.instruments.shares()
        return [
            Instrument(
                figi=share.figi,
                isin=share.isin,
                name=share.name,
                ticker=share.ticker,
                currency=str(getattr(share, "currency", "")),
                uid=share.uid,
            )
            for share in response.instruments
        ]

    def get_last_price(self, share) -> PricePoint:
        client_class = self._client()
        with client_class(self.token) as client:
            response = client.market_data.get_last_prices(figi=[share.figi])
        prices = list(getattr(response, "last_prices", []))
        if not prices:
            raise LookupError(f"No last price returned for figi {share.figi}")
        quote = next(
            (item for item in prices if getattr(item, "figi", None) == share.figi),
            prices[0],
        )
        return PricePoint(
            price=quotation_to_decimal(quote.price),
            time=quote.time,
        )

    def get_candles(self, share, days: int = 180) -> list[Candle]:
        client_class = self._client()
        from tinkoff.invest import CandleInterval

        from_ = datetime.now(timezone.utc) - timedelta(days=days)
        result = []
        with client_class(self.token) as client:
            for candle in client.get_all_candles(
                figi=share.figi,
                from_=from_,
                interval=CandleInterval.CANDLE_INTERVAL_DAY,
            ):
                result.append(
                    Candle(
                        time=candle.time,
                        close=quotation_to_decimal(candle.close),
                    )
                )
        return result


def get_provider(name: str | None = None) -> MarketDataProvider:
    provider_name = (name or settings.MARKET_DATA_PROVIDER or "demo").strip().lower()
    if provider_name == "demo":
        return DemoMarketDataProvider()
    if provider_name == "tinkoff":
        return TinkoffMarketDataProvider(settings.TINKOFF_TOKEN)
    raise ProviderConfigurationError(
        f"Unknown MARKET_DATA_PROVIDER={provider_name!r}; use 'demo' or 'tinkoff'"
    )
