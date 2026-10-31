from rest_framework import serializers

from dashboard.models import Share, generate_uid


class ShareSerializer(serializers.ModelSerializer):
    uid = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="Необязательно; при пустом значении будет создан автоматически.",
    )

    class Meta:
        model = Share
        fields = (
            "id",
            "figi",
            "isin",
            "name",
            "ticker",
            "currency",
            "uid",
            "last_price",
            "is_trend_high",
            "updated_at",
        )

    def validate_uid(self, value):
        return value or generate_uid()
