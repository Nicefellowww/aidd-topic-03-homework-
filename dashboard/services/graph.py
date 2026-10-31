from plotly import graph_objects as go
from plotly.io import to_html

from config.settings import logger

from .providers import get_provider


def get_graph(share, provider=None, days: int = 180):
    """Build a Plotly price chart from the configured market data provider.

    External failures must not break the detail page, therefore an explanatory
    HTML fragment is returned instead of raising an exception.
    """

    try:
        provider = provider or get_provider()
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
        autosize=True,
        margin={"l": 60, "r": 24, "t": 24, "b": 64},
        xaxis_title="Дата",
        yaxis_title=f"Цена, {share.currency}",
    )
    figure.update_xaxes(automargin=True, nticks=6, tickangle=0, title_standoff=12)
    figure.update_yaxes(automargin=True, title_standoff=12)
    return to_html(
        figure,
        include_plotlyjs=False,
        full_html=False,
        config={"displayModeBar": False, "responsive": True},
    )



def get_history_graph(points, currency):
    """Render only persisted quotes; no provider calls and no synthetic fallback."""
    if not points:
        return ''
    figure = go.Figure(data=[go.Scatter(
        x=[point.quoted_at for point in points],
        y=[float(point.price) for point in points], mode='lines+markers', name='Сохранённая цена',
    )])
    figure.update_layout(autosize=True, margin={'l': 60, 'r': 24, 't': 24, 'b': 64},
                         xaxis_title='Время котировки', yaxis_title=f'Цена, {currency}')
    figure.update_xaxes(automargin=True, nticks=6, tickangle=0, title_standoff=12)
    figure.update_yaxes(automargin=True, title_standoff=12)
    return to_html(figure, include_plotlyjs=False, full_html=False,
                   config={'displayModeBar': False, 'responsive': True})
