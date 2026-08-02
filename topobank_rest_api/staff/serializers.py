from django.contrib.auth import get_user_model
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from topobank.analysis.models import WorkflowResult
from topobank.taskapp.models import TaskStateModel

from . import queries

#: Truncation length for error messages in the list view. The full traceback
#: stays available on the regular analysis detail endpoint.
MAX_ERROR_LENGTH = 300


class StaffUserSerializer(serializers.ModelSerializer):
    """
    One row of the staff user dashboard.

    Every derived value is read off an annotation set up in
    :mod:`topobank_rest_api.staff.queries`; nothing here may touch a related
    manager, or the list view degenerates into an N+1.
    """

    class Meta:
        model = get_user_model()
        fields = [
            "id",
            "name",
            "username",
            "email",
            "orcid",
            "terms_status",
            "terms_accepted_on",
            "date_joined",
            "last_login",
            "num_surfaces",
            "num_topographies",
            "is_active",
            "is_staff",
            "admin_url",
        ]
        read_only_fields = fields

    orcid = serializers.CharField(read_only=True, allow_null=True)
    num_surfaces = serializers.IntegerField(read_only=True)
    num_topographies = serializers.IntegerField(read_only=True)
    terms_accepted_on = serializers.DateTimeField(read_only=True, allow_null=True)
    terms_status = serializers.SerializerMethodField()
    admin_url = serializers.SerializerMethodField()

    def get_terms_status(self, obj) -> str:
        num_active = self.context.get("num_active_terms")
        if num_active is None:
            # The terms-and-conditions app is not installed here.
            return queries.TERMS_UNAVAILABLE
        if obj.pk in self.context.get("terms_exempt_ids", set()):
            return queries.TERMS_EXEMPT
        if num_active == 0:
            return queries.TERMS_NOT_REQUIRED
        accepted = getattr(obj, "num_accepted_terms", 0) or 0
        if accepted >= num_active:
            return queries.TERMS_ACCEPTED
        if accepted > 0:
            return queries.TERMS_PARTIAL
        return queries.TERMS_NOT_ACCEPTED

    def get_admin_url(self, obj) -> str:
        meta = obj._meta
        try:
            return reverse(
                f"admin:{meta.app_label}_{meta.model_name}_change", args=[obj.pk]
            )
        except NoReverseMatch:
            # The user model is not registered with the admin in this
            # deployment (or the admin is not installed at all).
            return None


class StaffTaskSerializer(serializers.ModelSerializer):
    """One row of the staff task dashboard."""

    class Meta:
        model = WorkflowResult
        fields = [
            "id",
            "name",
            "workflow_name",
            "task_state",
            "task_state_display",
            "is_running",
            "subject",
            "created_by",
            "queue",
            "task_id",
            "task_submission_time",
            "task_start_time",
            "task_end_time",
            "duration",
            "task_memory",
            "task_error",
            "created_at",
        ]
        read_only_fields = fields

    # Read the stored state rather than TaskStateModel.get_task_state(), which
    # would query the Celery result backend once per row.
    task_state = serializers.CharField(read_only=True)
    task_state_display = serializers.SerializerMethodField()
    is_running = serializers.SerializerMethodField()
    subject = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    queue = serializers.SerializerMethodField()
    duration = serializers.SerializerMethodField()
    task_error = serializers.SerializerMethodField()

    def get_task_state_display(self, obj: WorkflowResult) -> str:
        return dict(TaskStateModel.TASK_STATE_CHOICES).get(
            obj.task_state, obj.task_state
        )

    def get_is_running(self, obj: WorkflowResult) -> bool:
        return obj.task_state == TaskStateModel.STARTED

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "properties": {
                "type": {"type": "string"},
                "id": {"type": "integer", "nullable": True},
                "name": {"type": "string"},
                "count": {"type": "integer"},
            },
        }
    )
    def get_subject(self, obj: WorkflowResult) -> dict:
        if obj.subject_topography_id is not None:
            topography = obj.subject_topography
            return {
                "type": "measurement",
                "id": topography.id,
                "name": topography.name,
                "surface_id": topography.surface_id,
                "count": 1,
            }
        if obj.subject_surface_id is not None:
            surface = obj.subject_surface
            return {
                "type": "dataset",
                "id": surface.id,
                "name": surface.name,
                "count": 1,
            }
        if obj.subject_tag_id is not None:
            tag = obj.subject_tag
            return {"type": "tag", "id": tag.id, "name": tag.name, "count": 1}

        # Surface-set analyses: `surfaces` is prefetched by the dashboard
        # queryset, so this does not hit the database.
        surfaces = list(obj.surfaces.all())
        if len(surfaces) == 1:
            return {
                "type": "dataset",
                "id": surfaces[0].id,
                "name": surfaces[0].name,
                "count": 1,
            }
        if surfaces:
            return {
                "type": "datasets",
                "id": None,
                "name": f"{len(surfaces)} datasets",
                "count": len(surfaces),
            }
        return None

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "username": {"type": "string"},
            },
        }
    )
    def get_created_by(self, obj: WorkflowResult) -> dict:
        user = obj.created_by
        if user is None:
            return None
        username = user.get_username()
        # `name` is not a reliable label. It is a plain non-blank-validated
        # CharField, and the production user model fills it from first/last
        # name, which yields a whitespace-only string for accounts that have
        # neither (the anonymous user, for one). Fall back to the username so
        # that clients never receive an empty label, which renders as "this
        # task has no user".
        name = (getattr(user, "name", "") or "").strip()
        return {"id": user.id, "name": name or username, "username": username}

    def get_queue(self, obj: WorkflowResult) -> str:
        try:
            return obj.get_celery_queue()
        except Exception:
            # Resolving the queue goes through the workflow registry, which
            # has nothing to offer for results of a workflow that has since
            # been unregistered (e.g. a removed plugin). Those rows should
            # still be listed.
            return None

    def get_duration(self, obj: WorkflowResult) -> float:
        if obj.task_start_time is None:
            return None
        if obj.task_end_time is not None:
            return (obj.task_end_time - obj.task_start_time).total_seconds()
        if obj.task_state == TaskStateModel.STARTED:
            # Still running: report elapsed time so the dashboard can show a
            # task that has been going for an hour as such.
            return (timezone.now() - obj.task_start_time).total_seconds()
        return None

    def get_task_error(self, obj: WorkflowResult) -> str:
        error = obj.task_error or ""
        if len(error) > MAX_ERROR_LENGTH:
            return error[:MAX_ERROR_LENGTH] + "…"
        return error


class WorkerSerializer(serializers.Serializer):
    """A single Celery worker as reported by ``app.control.inspect``."""

    nodename = serializers.CharField(read_only=True)
    hostname = serializers.CharField(read_only=True)
    concurrency = serializers.IntegerField(read_only=True)
    min_concurrency = serializers.IntegerField(read_only=True, allow_null=True)
    pool = serializers.CharField(read_only=True, allow_null=True)
    pid = serializers.IntegerField(read_only=True, allow_null=True)
    uptime = serializers.IntegerField(read_only=True, allow_null=True)
    processed = serializers.IntegerField(read_only=True)
    software = serializers.CharField(read_only=True, allow_null=True)
    queues = serializers.ListField(child=serializers.CharField(), read_only=True)
    active_tasks = serializers.IntegerField(read_only=True)
    reserved_tasks = serializers.IntegerField(read_only=True)


class WorkerStateSerializer(serializers.Serializer):
    """The worker fleet as a whole."""

    available = serializers.BooleanField(read_only=True)
    reason = serializers.CharField(read_only=True, allow_null=True)
    workers = WorkerSerializer(many=True, read_only=True)
    num_workers = serializers.IntegerField(read_only=True)
    total_concurrency = serializers.IntegerField(read_only=True)
    active_tasks = serializers.IntegerField(read_only=True)
    reserved_tasks = serializers.IntegerField(read_only=True)
    free_slots = serializers.IntegerField(read_only=True)
    queues = serializers.ListField(child=serializers.CharField(), read_only=True)
