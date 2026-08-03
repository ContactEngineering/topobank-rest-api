from django.conf import settings
from django.urls import path, re_path
from rest_framework.routers import DefaultRouter, SimpleRouter
from topobank.analysis import workflows

import topobank_rest_api.analysis.v1.views as v1
import topobank_rest_api.analysis.v2.views as v2

router = DefaultRouter() if settings.DEBUG else SimpleRouter()
router.register(r"api/configuration", v1.ConfigurationView, basename="configuration")
router.register(r"api/workflow", v1.WorkflowView, basename="workflow")
router.register(r"api/result", v1.ResultView, basename="result")
router.register(r"v2/configurations", v2.ConfigurationView, basename="configuration-v2")
router.register(r"v2/workflows", v2.WorkflowView, basename="workflow-v2")
router.register(r"v2/results", v2.ResultView, basename="result-v2")
router.register(
    r"v2/zip-container",
    v2.ResultZipContainerViewSet,
    basename="result-zip-container-v2",
)

urlpatterns = router.urls

app_name = workflows.APP_NAME
urlpatterns += [
    #
    # v1 API routes
    #
    # GET
    # * Get pending or running analyses
    path("api/pending", view=v1.pending, name="pending"),
    # GET
    # * Get dependent analyses
    path(
        "api/result/<int:workflow_id>/dependencies",
        view=v1.dependencies,
        name="dependencies",
    ),
    # GET
    # * Return named/save results
    path(
        "api/named-result",
        view=v1.named_result,
        name="named-result-list",
    ),
    # GET
    # * Triggers analyses if not yet running
    # * Return state of analyses
    # * Return plot configuration for finished analyses
    # This is a post request because the request parameters are complex.
    path(
        f"api/card/{workflows.VIZ_SERIES}/<str:workflow>",
        view=v1.series_card_view,
        name=f"card-{workflows.VIZ_SERIES}",
    ),
    # GET
    # * Return total number of analyses
    path("api/statistics/", view=v1.statistics, name="statistics"),
    # GET
    # * Return memory usage of individual analyses
    path("api/memory-usage/", view=v1.memory_usage, name="memory-usage"),
    #
    # v2 API routes
    #
    # POST
    # * Start bundling the files of the given results into a ZIP archive.
    #   Returns the container, whose state is then polled on the
    #   'result-zip-container-v2-detail' route.
    re_path(
        r"v2/download-results/(?P<result_ids>[\d,]+)/$",
        view=v2.download_results,
        name="download-results-v2",
    ),
]
