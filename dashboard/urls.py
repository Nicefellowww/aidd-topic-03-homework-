from django.urls import include, path

from dashboard.views import (
    ShareCreateView,
    ShareDeleteView,
    ShareDetailView,
    ShareListView,
    ShareUpdateView,
)

app_name = "dashboard"

from . import investing_views as investing

urlpatterns = [
    path("watches/", investing.watches, name="watches"),
    path("watches/<int:pk>/delete/", investing.watch_delete, name="watch_delete"),
    path("notifications/<int:pk>/read/", investing.notification_read, name="notification_read"),
    path("portfolios/", investing.portfolios, name="portfolios"),
    path("portfolios/<int:pk>/", investing.portfolio, name="portfolio"),
    path("strategies/", investing.strategies, name="strategies"),
    path("strategies/<int:pk>/", investing.strategy, name="strategy"),
    path("history/<int:pk>/", investing.history, name="history"),
    path("", ShareListView.as_view(), name="index"),
    path("<int:pk>", ShareDetailView.as_view(), name="detail"),
    path("create", ShareCreateView.as_view(), name="create"),
    path("update/<int:pk>", ShareUpdateView.as_view(), name="update"),
    path("delete/<int:pk>", ShareDeleteView.as_view(), name="delete"),
    path("api/", include("dashboard.api.urls")),
]
