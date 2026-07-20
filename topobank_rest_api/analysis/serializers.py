from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.reverse import reverse
from topobank.analysis.models import Configuration, WorkflowResult
from topobank.analysis.workflows import VIZ_SERIES
from topobank.manager.models import Surface, Tag, Topography

import topobank_rest_api.taskapp.serializers
from topobank_rest_api.supplib.mixins import StrictFieldMixin
from topobank_rest_api.supplib.serializers import UserField


def _visualization_type(workflow):
    """Return the visualization (card) type for a workflow.

    Implementations declare it via ``Meta.visualization_type``; workflows that
    do not are rendered with the default (series) card.
    """
    impl = workflow.implementation
    if impl is not None:
        return getattr(impl.Meta, "visualization_type", VIZ_SERIES)
    return VIZ_SERIES


class ConfigurationSerializer(StrictFieldMixin, serializers.HyperlinkedModelSerializer):
    """Serializer for Configuration model."""
    class Meta:
        model = Configuration
        fields = ["valid_since", "versions"]

    versions = serializers.SerializerMethodField()

    @extend_schema_field(serializers.DictField(child=serializers.CharField()))
    def get_versions(self, obj):
        versions = {}
        for version in obj.versions.all():
            versions[str(version.dependency)] = version.number_as_string()
        return versions


class WorkflowListSerializer(StrictFieldMixin, serializers.Serializer):
    """Serializer for Workflow (plain Python class, not a DB model)."""

    url = serializers.HyperlinkedIdentityField(
        view_name="analysis:workflow-detail", lookup_field="name", read_only=True
    )
    name = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    visualization_type = serializers.SerializerMethodField()

    @extend_schema_field(serializers.CharField())
    def get_visualization_type(self, obj) -> str:
        return _visualization_type(obj)


class WorkflowDetailSerializer(StrictFieldMixin, serializers.Serializer):
    """Serializer for Workflow (plain Python class, not a DB model)."""

    url = serializers.HyperlinkedIdentityField(
        view_name="analysis:workflow-detail", lookup_field="name", read_only=True
    )
    name = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    visualization_type = serializers.SerializerMethodField()
    subject_types = serializers.SerializerMethodField()

    @extend_schema_field(serializers.CharField())
    def get_visualization_type(self, obj) -> str:
        return _visualization_type(obj)
    kwargs_schema = serializers.SerializerMethodField()
    outputs_schema = serializers.SerializerMethodField()

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_subject_types(self, obj):
        subject_types = []
        if obj.has_implementation(Surface):
            subject_types.append("surface")
        if obj.has_implementation(Topography):
            subject_types.append("topography")
        if obj.has_implementation(Tag):
            subject_types.append("tag")
        return subject_types

    @extend_schema_field(serializers.DictField())
    def get_kwargs_schema(self, obj):
        return obj.get_kwargs_schema()

    @extend_schema_field(serializers.ListField())
    def get_outputs_schema(self, obj):
        return obj.get_outputs_schema()


class SubjectSerializer(StrictFieldMixin, serializers.Serializer):
    """Serializer for WorkflowResult subject fields."""
    tag = serializers.HyperlinkedRelatedField(
        view_name="manager:tag-api-detail", read_only=True, lookup_field="name"
    )
    topography = serializers.HyperlinkedRelatedField(
        view_name="manager:topography-api-detail", read_only=True
    )
    surface = serializers.HyperlinkedRelatedField(
        view_name="manager:surface-api-detail", read_only=True
    )


class ResultSerializer(
    StrictFieldMixin, topobank_rest_api.taskapp.serializers.TaskStateModelSerializer
):
    """Serializer for WorkflowResult model."""
    class Meta:
        model = WorkflowResult
        fields = [
            "url",
            "id",
            "api",
            "dependencies_url",
            "function",
            "subject",
            "kwargs",
            "creation_time",
            "task_state",
            "task_progress",
            "task_messages",  # Informative message on the progress of the task
            "task_memory",
            "task_error",
            "task_traceback",
            "task_submission_time",
            "task_start_time",
            "task_end_time",
            "task_duration",
            "task_id",
            "launcher_task_id",
            "dois",
            "configuration",
            "folder",
            "name",
            "creator"
        ]
        read_only_fields = fields

    # Self
    url = serializers.HyperlinkedIdentityField(
        view_name="analysis:result-detail", read_only=True
    )
    dependencies_url = serializers.SerializerMethodField()
    api = serializers.SerializerMethodField()
    # WorkflowResult.function is a property returning Workflow(name=...) — read-only URL
    function = serializers.HyperlinkedRelatedField(
        view_name="analysis:workflow-detail", lookup_field="name", read_only=True
    )
    subject = serializers.SerializerMethodField()
    folder = serializers.HyperlinkedRelatedField(
        view_name="files:folder-api-detail", read_only=True
    )
    configuration = serializers.HyperlinkedRelatedField(
        view_name="analysis:configuration-detail", read_only=True
    )
    creation_time = serializers.DateTimeField(source="created_at", read_only=True)
    creator = UserField(source="created_by", read_only=True)

    @extend_schema_field(SubjectSerializer)
    def get_subject(self, obj: WorkflowResult):
        request = self.context.get("request")
        if obj.subject_topography_id:
            return {
                "topography": reverse(
                    "manager:topography-api-detail",
                    kwargs={"pk": obj.subject_topography_id},
                    request=request,
                ),
                "surface": None,
                "tag": None,
            }
        elif obj.subject_surface_id:
            return {
                "topography": None,
                "surface": reverse(
                    "manager:surface-api-detail",
                    kwargs={"pk": obj.subject_surface_id},
                    request=request,
                ),
                "tag": None,
            }
        elif obj.subject_tag_id:
            tag = Tag.objects.get(pk=obj.subject_tag_id)
            return {
                "topography": None,
                "surface": None,
                "tag": reverse(
                    "manager:tag-api-detail",
                    kwargs={"name": tag.name},
                    request=request,
                ),
            }
        return None

    @extend_schema_field(
        {
            "type": "object",
            "properties": {
                "set_name": {"type": "string"},
            },
            "required": ["set_name"],
        }
    )
    def get_api(self, obj: WorkflowResult) -> dict:
        return {
            "set_name": reverse(
                "analysis:set-name",
                kwargs={"workflow_id": obj.id},
                request=self.context["request"],
            ),
        }

    @extend_schema_field(serializers.URLField())
    def get_dependencies_url(self, obj):
        return reverse(
            "analysis:dependencies",
            kwargs={"workflow_id": obj.id},
            request=self.context["request"],
        )
