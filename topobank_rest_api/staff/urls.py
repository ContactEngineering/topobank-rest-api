from django.conf import settings
from django.urls import path
from rest_framework.routers import DefaultRouter, SimpleRouter

from . import views

app_name = "staff"

router = DefaultRouter() if settings.DEBUG else SimpleRouter()
router.register(r"api/user", views.StaffUserView, basename="user")
router.register(r"api/task", views.StaffTaskView, basename="task")

urlpatterns = router.urls + [
    # GET
    # * Registered Celery workers, their machines and their pool sizes
    path("api/worker/", view=views.workers, name="worker"),
]
