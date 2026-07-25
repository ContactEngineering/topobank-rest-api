from django.urls import include, path

from topobank_rest_api.views import entry_points

urlpatterns = [
    path("users/", include("topobank_rest_api.users.urls", namespace="users")),
    path("authorization/", include("topobank_rest_api.authorization.urls", namespace="authorization")),
    path("files/", include("topobank_rest_api.files.urls", namespace="files")),
    path("manager/", include("topobank_rest_api.manager.urls", namespace="manager")),
    path("analysis/", include("topobank_rest_api.analysis.urls", namespace="analysis")),
    path("staff/", include("topobank_rest_api.staff.urls", namespace="staff")),
    # API entry points
    path("api/", entry_points, name="entry-points"),
]
