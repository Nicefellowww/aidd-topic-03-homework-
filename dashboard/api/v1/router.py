from rest_framework import routers

from .views import ShareViewSet

router = routers.DefaultRouter()
router.register(r"shares", ShareViewSet)
