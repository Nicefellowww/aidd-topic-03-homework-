import logging
from plotly.graph_objs import Scatter, Figure
from plotly.offline import plot
from .market_data import MarketDataError, get_provider

logger = logging.getLogger('main')


def get_graph(share):
    try:
        candles = get_provider().candles(share)
    except MarketDataError:
        logger.warning('Chart unavailable for share %s', share.pk)
        return '<p>График недоступен: проверьте источник данных и подключение.</p>'
    figure = Figure(data=[Scatter(x=[item[0] for item in candles],
                                  y=[str(item[1]) for item in candles], mode='lines',
                                  name='Цена', marker_color='red')])
    figure.update_layout(height=440, autosize=True, margin=dict(l=65, r=20, t=35, b=80),
                         xaxis=dict(title='Дата (UTC)', automargin=True),
                         yaxis=dict(title='Цена', automargin=True))
    return plot(figure, output_type='div', include_plotlyjs=True, show_link=False,
                config={'responsive': True})


def history_graph(rows):
    figure = Figure()
    for currency in sorted({row.currency for row in rows}):
        points = [row for row in rows if row.currency == currency]
        figure.add_trace(Scatter(x=[row.timestamp for row in points], y=[str(row.price) for row in points],
                                mode='lines+markers', name=currency))
    figure.update_layout(height=440, autosize=True, margin=dict(l=65, r=20, t=35, b=80),
                         xaxis=dict(title='Время котировки (UTC)', automargin=True),
                         yaxis=dict(title='Цена', automargin=True))
    return plot(figure, output_type='div', include_plotlyjs=True, config={'responsive': True})
