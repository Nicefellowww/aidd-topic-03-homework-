from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from dashboard.models import Share
from dashboard.services.providers import (
    Instrument,
    PricePoint,
    quotation_to_decimal,
)
from dashboard.tasks import calculate_trend, update_last_price

User = get_user_model()


def create_share(**overrides):
    data = {
        "figi": "BBG000B9XRY4",
        "isin": "US0378331005",
        "name": "Apple",
        "ticker": "AAPL",
        "currency": "usd",
        "uid": "a9eb4238-eba9-488c-b102-b6140fd08e38",
        "last_price": Decimal("100.500000000"),
        "is_trend_high": True,
    }
    data.update(overrides)
    return Share.objects.create(**data)


class ShareModelTests(TestCase):
    def test_decimal_price_keeps_fractional_part(self):
        share = create_share(last_price=Decimal("123.456789123"))
        share.refresh_from_db()
        self.assertEqual(share.last_price, Decimal("123.456789123"))
        self.assertEqual(share.price_display, "123.456789123")

    def test_uid_is_generated_when_blank(self):
        share = Share.objects.create(
            figi="FIGI-1",
            isin="ISIN-1",
            name="No uid",
            ticker="NOUID",
            currency="rub",
            uid="",
        )
        self.assertTrue(share.uid)
        self.assertNotEqual(share.uid, "")

    def test_quotation_to_decimal(self):
        quotation = SimpleNamespace(units=12, nano=345000000)
        self.assertEqual(quotation_to_decimal(quotation), Decimal("12.345"))


class ShareHtmlTests(TestCase):
    def setUp(self):
        self.share = create_share()
        self.user = User.objects.create_user(
            username="user@example.com",
            email="user@example.com",
            password="V3ry-Str0ng-Pass!",
        )

    def test_list_is_public(self):
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Apple")

    @override_settings(MARKET_DATA_PROVIDER="demo")
    def test_demo_source_is_visible(self):
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Демонстрационный источник данных")

    @override_settings(MARKET_DATA_PROVIDER="demo")
    def test_detail_is_public_and_has_graph(self):
        response = self.client.get(reverse("dashboard:detail", args=[self.share.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Apple")
        self.assertContains(response, "plotly")

    def test_detail_missing_share_returns_404(self):
        response = self.client.get(reverse("dashboard:detail", args=[99999]))
        self.assertEqual(response.status_code, 404)

    def test_write_pages_require_authentication(self):
        for name, args in (
            ("dashboard:create", []),
            ("dashboard:update", [self.share.pk]),
            ("dashboard:delete", [self.share.pk]),
        ):
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse("dashboard:index"))

    def test_authenticated_user_can_create_update_and_delete(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dashboard:create"),
            {
                "figi": "FIGI-NEW",
                "isin": "ISIN-NEW",
                "name": "New share",
                "ticker": "NEW",
                "currency": "rub",
                "uid": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        new_share = Share.objects.get(figi="FIGI-NEW")
        self.assertTrue(new_share.uid)

        response = self.client.post(
            reverse("dashboard:update", args=[new_share.pk]),
            {
                "figi": "FIGI-NEW",
                "isin": "ISIN-NEW",
                "name": "Updated share",
                "ticker": "NEW",
                "currency": "rub",
                "uid": new_share.uid,
            },
        )
        self.assertEqual(response.status_code, 302)
        new_share.refresh_from_db()
        self.assertEqual(new_share.name, "Updated share")

        response = self.client.post(
            reverse("dashboard:delete", args=[new_share.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Share.objects.filter(pk=new_share.pk).exists())

    def test_service_fields_are_not_in_html_form(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard:create"))
        self.assertNotContains(response, 'name="last_price"')
        self.assertNotContains(response, 'name="is_trend_high"')


class ShareApiTests(APITestCase):
    def setUp(self):
        self.share = create_share()
        self.user = User.objects.create_user(
            username="api@example.com",
            email="api@example.com",
            password="V3ry-Str0ng-Pass!",
        )
        self.second_company = {
            "figi": "BBG000B9XRY5",
            "isin": "US0378331004",
            "name": "Company_test",
            "ticker": "TESTTEST",
            "currency": "usd",
        }

    def test_read_is_public(self):
        response = self.client.get("/api/v1/shares/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"][0]["figi"], self.share.figi)

    def test_write_requires_authentication(self):
        response = self.client.post(
            "/api/v1/shares/", self.second_company, format="json"
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
        self.assertEqual(Share.objects.count(), 1)

    def test_create_without_uid_generates_unique_uid(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/v1/shares/", self.second_company, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        first = Share.objects.get(figi=self.second_company["figi"])
        self.assertTrue(first.uid)

        third_company = dict(
            self.second_company,
            figi="BBG000B9XRY6",
            isin="US0378331003",
            ticker="TESTTES2",
            name="Third",
        )
        response = self.client.post("/api/v1/shares/", third_company, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        second = Share.objects.get(figi=third_company["figi"])
        self.assertNotEqual(first.uid, second.uid)

    def test_update_and_delete_require_authentication(self):
        url = f"/api/v1/shares/{self.share.pk}/"
        response = self.client.patch(url, {"name": "Hacked"}, format="json")
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
        response = self.client.delete(url)
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

        self.client.force_authenticate(self.user)
        response = self.client.patch(url, {"name": "Updated"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.share.refresh_from_db()
        self.assertEqual(self.share.name, "Updated")

        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_filters_search_and_ordering(self):
        create_share(
            figi="FIGI-MSFT",
            isin="ISIN-MSFT",
            name="Microsoft",
            ticker="MSFT",
            uid="uid-msft",
        )
        create_share(
            figi="FIGI-SBER",
            isin="ISIN-SBER",
            name="Sberbank",
            ticker="SBER",
            uid="uid-sber",
        )

        response = self.client.get("/api/v1/shares/?ticker=MSFT")
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["ticker"], "MSFT")

        response = self.client.get("/api/v1/shares/?search=Micro")
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["name"], "Microsoft")

        response = self.client.get("/api/v1/shares/?ordering=-name")
        names = [item["name"] for item in response.data["results"]]
        self.assertEqual(names, sorted(names, reverse=True))

    def test_api_reports_data_source_header(self):
        response = self.client.get("/api/v1/shares/")
        self.assertEqual(response["X-Market-Data-Source"], "demo")

    def test_detail_invalid_returns_404(self):
        response = self.client.get("/api/v1/shares/99999/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class PriceUpdateTests(TestCase):
    def test_calculate_trend(self):
        self.assertIsNone(calculate_trend(None, Decimal("10")))
        self.assertIsNone(calculate_trend(Decimal("10"), Decimal("10")))
        self.assertTrue(calculate_trend(Decimal("10"), Decimal("10.01")))
        self.assertFalse(calculate_trend(Decimal("10"), Decimal("9.99")))

    @patch("dashboard.tasks.get_last_data")
    def test_task_updates_price_trend_and_updated_at(self, get_last_data_mock):
        growing = create_share(ticker="GROW", figi="FIGI-GROW", uid="uid-grow")
        falling = create_share(
            ticker="FALL",
            figi="FIGI-FALL",
            uid="uid-fall",
            last_price=Decimal("100.00"),
        )
        first_update = create_share(
            ticker="FIRST",
            figi="FIGI-FIRST",
            uid="uid-first",
            last_price=None,
            is_trend_high=None,
        )
        prices = {
            "GROW": Decimal("101.123456789"),
            "FALL": Decimal("99.5"),
            "FIRST": Decimal("42.25"),
        }
        get_last_data_mock.side_effect = lambda share: [
            prices[share.ticker],
            datetime.now(dt_timezone.utc),
        ]

        updated = update_last_price.run()

        self.assertEqual(updated, 3)
        growing.refresh_from_db()
        falling.refresh_from_db()
        first_update.refresh_from_db()
        self.assertEqual(growing.last_price, Decimal("101.123456789"))
        self.assertTrue(growing.is_trend_high)
        self.assertFalse(falling.is_trend_high)
        self.assertIsNone(first_update.is_trend_high)
        self.assertIsNotNone(growing.updated_at)
        self.assertIsNotNone(falling.updated_at)
        self.assertIsNotNone(first_update.updated_at)

    @override_settings(MARKET_DATA_PROVIDER="demo")
    def test_demo_get_last_data_returns_decimal(self):
        from dashboard.services.market_data import get_last_data

        share = create_share(ticker="DEMOAAPL", figi="DEMO-BBG-AAPL")
        price, quote_time = get_last_data(share)
        self.assertIsInstance(price, Decimal)
        self.assertEqual(price, price.quantize(Decimal("0.0001")))
        self.assertIsNotNone(quote_time)


class GraphTests(TestCase):
    @override_settings(MARKET_DATA_PROVIDER="demo")
    def test_demo_graph_is_generated(self):
        from dashboard.services.graph import get_graph

        share = create_share(ticker="DEMOAAPL", figi="DEMO-BBG-AAPL")
        html = get_graph(share)
        self.assertIn("plotly", html)
        self.assertNotIn("временно недоступны", html)

    def test_provider_failure_does_not_break_page(self):
        from dashboard.services.graph import get_graph

        share = create_share()
        provider = Mock()
        provider.get_candles.side_effect = RuntimeError("API down")
        html = get_graph(share, provider=provider)
        self.assertIn("временно недоступны", html)


class AddSharesCommandTests(TestCase):
    def test_demo_import_is_idempotent(self):
        call_command("add_shares", provider="demo", verbosity=0)
        first_count = Share.objects.count()
        call_command("add_shares", provider="demo", verbosity=0)
        self.assertEqual(Share.objects.count(), first_count)
        self.assertGreater(first_count, 0)
        self.assertTrue(Share.objects.filter(name__contains="демонстрационные").exists())

    def test_reimport_updates_existing_figi(self):
        first = Mock(is_demo=True)
        first.list_shares.return_value = [
            Instrument(
                figi="FIGI-IMPORT",
                isin="ISIN-IMPORT",
                name="Old name",
                ticker="IMP",
                currency="rub",
                uid="uid-import",
            )
        ]
        second = Mock(is_demo=True)
        second.list_shares.return_value = [
            Instrument(
                figi="FIGI-IMPORT",
                isin="ISIN-IMPORT",
                name="New name",
                ticker="IMP",
                currency="rub",
                uid="uid-import",
            )
        ]

        with patch(
            "dashboard.management.commands.add_shares.get_provider",
            return_value=first,
        ):
            call_command("add_shares", verbosity=0)
        with patch(
            "dashboard.management.commands.add_shares.get_provider",
            return_value=second,
        ):
            call_command("add_shares", verbosity=0)

        self.assertEqual(Share.objects.filter(figi="FIGI-IMPORT").count(), 1)
        self.assertEqual(Share.objects.get(figi="FIGI-IMPORT").name, "New name")
