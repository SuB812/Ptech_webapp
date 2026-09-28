"""Bid project routes. Mounted at /api/ by config.urls."""

from rest_framework.routers import DefaultRouter

from projects.views import BidProjectViewSet

router = DefaultRouter()
router.register(r"projects", BidProjectViewSet, basename="project")

urlpatterns = router.urls
