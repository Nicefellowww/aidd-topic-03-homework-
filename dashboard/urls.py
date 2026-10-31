from django.urls import include, path

from dashboard.views import (
    ShareCreateView,
    ShareDeleteView,
    ShareDetailView,
    ShareListView,
    ShareUpdateView,
)

from . import investment_views as investments

app_name = "dashboard"

urlpatterns = [
    path('watchlist/', investments.watchlist, name='watchlist'),
    path('watchlist/<int:pk>/edit/', investments.watch_edit, name='watch_edit'),
    path('watchlist/<int:pk>/delete/', investments.watch_delete, name='watch_delete'),
    path('watchlist/<int:pk>/check/', investments.watch_check, name='watch_check'),
    path('notifications/', investments.notifications, name='notifications'),
    path('notifications/<int:pk>/read/', investments.notification_read, name='notification_read'),
    path('portfolios/', investments.portfolios, name='portfolios'),
    path('portfolios/<int:pk>/', investments.portfolio, name='portfolio'),
    path('strategies/', investments.strategies, name='strategies'),
    path('strategies/<int:pk>/', investments.strategy, name='strategy'),
    path('strategies/<int:pk>/run/', investments.strategy_run, name='strategy_run'),
    path('history/<int:pk>/', investments.history, name='history'),
    path("", ShareListView.as_view(), name="index"),
    path("<int:pk>", ShareDetailView.as_view(), name="detail"),
    path("create", ShareCreateView.as_view(), name="create"),
    path("update/<int:pk>", ShareUpdateView.as_view(), name="update"),
    path("delete/<int:pk>", ShareDeleteView.as_view(), name="delete"),
    path("api/", include("dashboard.api.urls")),
]
