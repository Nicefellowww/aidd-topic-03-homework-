from django_filters import rest_framework as filters
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.filters import OrderingFilter, SearchFilter

from dashboard.models import Share

from .serializer import ShareSerializer


class ShareFilter(filters.FilterSet):
    class Meta:
        model = Share
        fields = ("name", "ticker")


class ShareViewSet(viewsets.ModelViewSet):
    serializer_class = ShareSerializer
    queryset = Share.objects.order_by("name", "pk")
    permission_classes = [IsAuthenticatedOrReadOnly]
    ordering = ["name", "pk"]
    filter_backends = (OrderingFilter, filters.DjangoFilterBackend, SearchFilter)
    filterset_class = ShareFilter
    ordering_fields = ["name", "ticker"]
    search_fields = ["name", "ticker"]

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            raise ValidationError('Акция используется в истории или персональных данных и не может быть удалена.')
