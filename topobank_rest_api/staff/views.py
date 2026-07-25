from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import filters, mixins, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from topobank.taskapp.models import TaskStateModel

from topobank_rest_api.supplib.pagination import TopobankPaginator

from . import queries
from .celery_inspect import get_worker_state
from .filters import NullsLastOrderingFilter, TaskSearchFilter
from .permissions import IsStaffUser
from .serializers import StaffTaskSerializer, StaffUserSerializer, WorkerStateSerializer

VALID_TASK_STATES = {state for state, _ in TaskStateModel.TASK_STATE_CHOICES}


class StaffUserView(viewsets.GenericViewSet, mixins.ListModelMixin):
    """
    Instance-wide list of users, for staff.

    Unlike the regular user endpoint this is not restricted to users you share
    a group with, and it carries the per-user object counts and terms-of-use
    acceptance state that the dashboard displays.
    """

    serializer_class = StaffUserSerializer
    permission_classes = [IsStaffUser]
    pagination_class = TopobankPaginator
    filter_backends = [filters.SearchFilter, NullsLastOrderingFilter]
    search_fields = ["name", "username", "email", "orcid"]
    ordering_fields = [
        "name",
        "username",
        "email",
        "date_joined",
        "last_login",
        "num_surfaces",
        "num_topographies",
        "num_accepted_terms",
        "terms_accepted_on",
        "orcid",
        "is_staff",
        "is_active",
    ]
    ordering = ("-date_joined",)

    def get_terms_ids(self):
        if not hasattr(self, "_terms_ids"):
            self._terms_ids = queries.active_terms_ids()
        return self._terms_ids

    def get_queryset(self):
        return queries.user_dashboard_queryset(self.get_terms_ids())

    def get_serializer_context(self):
        context = super().get_serializer_context()
        terms_ids = self.get_terms_ids()
        context["num_active_terms"] = None if terms_ids is None else len(terms_ids)
        context["terms_exempt_ids"] = getattr(self, "_terms_exempt_ids", set())
        return context

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "search",
                str,
                description="Match against name, username, email or ORCID iD.",
            ),
            OpenApiParameter(
                "ordering",
                str,
                description="Field to order by; prefix with '-' to reverse.",
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        users = page if page is not None else list(queryset)

        # Terms exemptions are permission lookups, so they are resolved once
        # for the whole page instead of via has_perm() per row.
        self._terms_exempt_ids = queries.terms_exempt_user_ids(
            [user.pk for user in users]
        )

        serializer = self.get_serializer(users, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class StaffTaskView(viewsets.GenericViewSet, mixins.ListModelMixin):
    """
    Instance-wide list of analysis tasks, for staff.

    Ordered so that the tasks currently occupying workers come first, which is
    what makes the list readable as a picture of the current system load.
    """

    serializer_class = StaffTaskSerializer
    permission_classes = [IsStaffUser]
    pagination_class = TopobankPaginator
    filter_backends = [TaskSearchFilter, NullsLastOrderingFilter]
    search_fields = [
        "workflow_name",
        "name",
        "task_error",
        "subject_topography__name",
        "subject_surface__name",
        "subject_tag__name",
        "created_by__name",
        "created_by__username",
    ]
    ordering_fields = [
        "workflow_name",
        "task_state",
        "task_submission_time",
        "task_start_time",
        "task_end_time",
        "task_memory",
        "activity_time",
        "created_at",
    ]
    #: Running first, then queued, then everything finished; most recent
    #: activity first within each group.
    ordering = ("state_rank", "-activity_time")

    def get_queryset(self):
        queryset = queries.task_dashboard_queryset()
        params = self.request.query_params

        states = [s for s in params.getlist("state") if s in VALID_TASK_STATES]
        if states:
            queryset = queryset.filter(task_state__in=states)

        workflow_name = params.get("workflow_name")
        if workflow_name:
            queryset = queryset.filter(workflow_name=workflow_name)

        created_by = params.get("created_by")
        if created_by:
            queryset = queryset.filter(created_by_id=created_by)

        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "state",
                str,
                description=(
                    "Task state to filter by; may be repeated. One of: "
                    + ", ".join(sorted(VALID_TASK_STATES))
                ),
            ),
            OpenApiParameter("workflow_name", str),
            OpenApiParameter("created_by", int, description="User ID."),
            OpenApiParameter(
                "search",
                str,
                description=(
                    "Match against workflow name, result name, error message, "
                    "subject name or creator. A full task UUID matches the "
                    "Celery task ID exactly."
                ),
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        responses={
            200: {
                "type": "object",
                "properties": {
                    "total": {"type": "integer"},
                    "by_state": {"type": "object"},
                    "running": {"type": "integer"},
                    "pending": {"type": "integer"},
                    "failed_last_24h": {"type": "integer"},
                    "finished_last_24h": {"type": "integer"},
                },
            }
        }
    )
    @action(detail=False, methods=["get"])
    def summary(self, request):
        """
        Instance-wide task counts.

        Deliberately computed over *all* tasks rather than the currently
        filtered list: this is the system-load headline, and it should not
        change when the operator narrows the table below it.
        """
        from topobank.analysis.models import WorkflowResult

        by_state = dict(
            WorkflowResult.objects.values_list("task_state")
            .order_by()
            .annotate(n=Count("pk"))
        )
        since = timezone.now() - timedelta(hours=24)
        recent = WorkflowResult.objects.filter(task_end_time__gte=since)

        pending = sum(
            by_state.get(state, 0)
            for state in (
                TaskStateModel.PENDING,
                TaskStateModel.PENDING_DEPENDENCIES,
                TaskStateModel.RETRY,
            )
        )

        return Response(
            {
                "total": sum(by_state.values()),
                "by_state": by_state,
                "running": by_state.get(TaskStateModel.STARTED, 0),
                "pending": pending,
                "failed_last_24h": recent.filter(
                    task_state=TaskStateModel.FAILURE
                ).count(),
                "finished_last_24h": recent.filter(
                    task_state=TaskStateModel.SUCCESS
                ).count(),
            }
        )


@extend_schema(
    description=(
        "State of the Celery worker fleet: how many workers are registered, "
        "which machines they run on, and how many tasks can run in parallel. "
        "Returns `available: false` (with HTTP 200) when the broker cannot be "
        "reached or no worker replies."
    ),
    responses={200: WorkerStateSerializer},
)
@api_view(["GET"])
@permission_classes([IsStaffUser])
def workers(request):
    # `refresh` bypasses the short-lived cache, for when an operator has just
    # started or stopped a worker and wants to see it immediately.
    use_cache = request.query_params.get("refresh") not in ("1", "true", "yes")
    return Response(WorkerStateSerializer(get_worker_state(use_cache=use_cache)).data)
