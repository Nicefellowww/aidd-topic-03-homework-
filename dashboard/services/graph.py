import logging
from plotly.graph_objs import Scatter
from plotly.offline import plot
from .market_data import MarketDataError, get_provider

logger = logging.getLogger('main')


def get_graph(share):
    try:
        candles = get_provider().candles(share)
    except MarketDataError:
        logger.warning('Chart unavailable for share %s', share.pk)
        return '<p>График недоступен: проверьте источник данных и подключение.</p>'
    return plot([Scatter(x=[item[0] for item in candles],
                         y=[str(item[1]) for item in candles], mode='lines',
                         name='Цена', marker_color='red')],
                output_type='div', include_plotlyjs=True, show_link=False)
