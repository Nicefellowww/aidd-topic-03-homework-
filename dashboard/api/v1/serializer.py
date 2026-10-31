from rest_framework import serializers

from dashboard.models import Share


class ShareSerializer(serializers.ModelSerializer):
    class Meta:
        read_only_fields = ("is_trend_high", "updated_at", "price_source")
        model = Share
        fields = (
            "id",
            "uid",
            "price_source",
            "figi",
            "isin",
            "name",
            "ticker",
            "currency",
            "last_price",
            "is_trend_high",
            "updated_at",
        )
