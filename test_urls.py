from django.urls import include, path

from topobank_rest_api.views import entry_points

urlpatterns = [
    path("users/", include("topobank_rest_api.users.urls", namespace="users")),
    path("organizations/", include("topobank_rest_api.organizations.urls", namespace="organizations")),
    path("authorization/", include("topobank_rest_api.authorization.urls", namespace="authorization")),
    path("files/", include("topobank_rest_api.files.urls", namespace="files")),
    path("manager/", include("topobank_rest_api.manager.urls", namespace="manager")),
    path("analysis/", include("topobank_rest_api.analysis.urls", namespace="analysis")),
    # API entry points
    path("api/", entry_points, name="entry-points"),
]
