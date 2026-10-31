"""Regressions for Decimal prices accidentally becoming Plotly categories."""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from plotly.offline import plot

from dashboard.services.graph import get_graph, history_graph


class NumericPriceGraphTests(SimpleTestCase):
    def setUp(self):
        self.prices = [Decimal('100'), Decimal('90'), Decimal('125')]
        start = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.times = [start + timedelta(minutes=i) for i in range(3)]

    def assert_numeric_chart(self, render, expected=None):
        # Inspect the JSON actually serialized by Plotly, not just Python input.
        figure = json.loads(render.call_args.args[0].to_json())
        values = figure['data'][0]['y']
        self.assertEqual(values, expected if expected is not None else [100, 90, 125])
        self.assertTrue(all(type(value) in (int, float) for value in values))
        self.assertLess(values[1], values[0])
        self.assertGreater(values[2], values[1])
        axis = figure['layout']['yaxis']
        self.assertEqual(axis['type'], 'linear')
        self.assertEqual(axis['tickmode'], 'auto')
        self.assertEqual(axis['nticks'], 6)
        self.assertEqual(axis['tickformat'], '.4~s')
        self.assertNotIn('categoryarray', axis)
        self.assertTrue(render.call_args.kwargs['config']['responsive'])

    def test_accumulated_history_uses_numeric_prices_and_linear_axis(self):
        rows = [SimpleNamespace(timestamp=stamp, price=price, currency='rub')
                for stamp, price in zip(self.times, self.prices)]
        with patch('dashboard.services.graph.plot', wraps=plot) as render:
            html = history_graph(rows)
        self.assert_numeric_chart(render)
        self.assertIn('Plotly.newPlot', html)
        self.assertEqual([row.price for row in rows], self.prices)
        self.assertTrue(all(isinstance(row.price, Decimal) for row in rows))

    def test_provider_candles_use_numeric_prices_without_changing_decimals(self):
        # Include a price whose full Decimal precision is beyond a JS number.
        exact = Decimal('123456789012345.123456789')
        candles = list(zip(self.times, self.prices)) + [(self.times[-1] + timedelta(minutes=1), exact)]
        with patch('dashboard.services.graph.get_provider') as provider, \
                patch('dashboard.services.graph.plot', wraps=plot) as render:
            provider.return_value.candles.return_value = candles
            get_graph(SimpleNamespace(pk=1))
        figure = json.loads(render.call_args.args[0].to_json())
        self.assertEqual(figure['data'][0]['y'][-1], float(exact))
        self.assert_numeric_chart(render, [100, 90, 125, float(exact)])
        self.assertEqual(candles[-1][1], Decimal('123456789012345.123456789'))
        self.assertTrue(all(isinstance(price, Decimal) for _, price in candles))
