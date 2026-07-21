from django.conf import settings
from rest_framework.routers import DefaultRouter, SimpleRouter

from . import views as v1

app_name = "users"

router = DefaultRouter() if settings.DEBUG else SimpleRouter()
router.register(r"v1/user", v1.UserViewSet, basename="user-v1")

urlpatterns = router.urls
