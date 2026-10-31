from plotly import graph_objects as go
from plotly.io import to_html

from config.settings import logger

from .providers import get_provider


def get_graph(share, provider=None, days: int = 180):
    """Build a Plotly price chart from the configured market data provider.

    External failures must not break the detail page, therefore an explanatory
    HTML fragment is returned instead of raising an exception.
    """

    provider = provider or get_provider()
    try:
        candles = provider.get_candles(share, days=days)
    except Exception:
        logger.exception("Unable to load candles for share id %s", share.id)
        return (
            '<p class="text-muted">Исторические данные временно недоступны.</p>'
        )

    if not candles:
        return '<p class="text-muted">Нет исторических данных.</p>'

    figure = go.Figure(
        data=[
            go.Scatter(
                x=[candle.time.date() for candle in candles],
                y=[float(candle.close) for candle in candles],
                mode="lines",
                name="Цена закрытия",
                opacity=0.8,
                line={"color": "red"},
            )
        ]
    )
    figure.update_layout(
        margin={"l": 40, "r": 20, "t": 20, "b": 40},
        xaxis_title="Дата",
        yaxis_title=f"Цена, {share.currency}",
    )
    return to_html(
        figure,
        include_plotlyjs=False,
        full_html=False,
        config={"displayModeBar": False},
    )
