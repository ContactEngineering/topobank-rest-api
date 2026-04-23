from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.reverse import reverse
from topobank.analysis.models import (
    Configuration,
    WorkflowResult,
    WorkflowSubject,
    resolve_workflow,
)
from topobank.manager.models import Surface, Tag, Topography

import topobank_rest_api.taskapp.serializers
from topobank_rest_api.supplib.mixins import StrictFieldMixin
from topobank_rest_api.supplib.serializers import UserField


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

    url = serializers.SerializerMethodField()
    name = serializers.CharField()
    display_name = serializers.CharField()

    @extend_schema_field(serializers.URLField())
    def get_url(self, obj):
        request = self.context.get("request")
        return reverse(
            "analysis:workflow-detail",
            kwargs={"name": obj.name},
            request=request,
        )


class WorkflowDetailSerializer(StrictFieldMixin, serializers.Serializer):
    """Serializer for Workflow (plain Python class, not a DB model)."""

    url = serializers.SerializerMethodField()
    name = serializers.CharField()
    display_name = serializers.CharField()
    subject_types = serializers.SerializerMethodField()
    kwargs_schema = serializers.SerializerMethodField()
    outputs_schema = serializers.SerializerMethodField()

    @extend_schema_field(serializers.URLField())
    def get_url(self, obj):
        request = self.context.get("request")
        return reverse(
            "analysis:workflow-detail",
            kwargs={"name": obj.name},
            request=request,
        )

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


class SubjectSerializer(
    StrictFieldMixin, serializers.HyperlinkedModelSerializer
):
    """Serializer for WorkflowSubject model."""
    class Meta:
        model = WorkflowSubject
        fields = ["id", "tag", "topography", "surface"]

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
    function = serializers.SerializerMethodField()
    subject = SubjectSerializer(source="subject_dispatch", read_only=True)
    folder = serializers.HyperlinkedRelatedField(
        view_name="files:folder-api-detail", read_only=True
    )
    configuration = serializers.HyperlinkedRelatedField(
        view_name="analysis:configuration-detail", read_only=True
    )
    creation_time = serializers.DateTimeField(source="created_at", read_only=True)
    creator = UserField(source="created_by", read_only=True)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_function(self, obj: WorkflowResult):
        if obj.workflow_name is None:
            return None
        request = self.context.get("request")
        return reverse(
            "analysis:workflow-detail",
            kwargs={"name": obj.workflow_name},
            request=request,
        )

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


class WorkflowField(serializers.Field):
    """
    Custom field for Workflow (plain Python class).

    - to_representation: returns URL pointing to workflow detail endpoint
    - to_internal_value: accepts workflow name or URL, returns the workflow name string
    """

    def to_representation(self, value):
        if value is None:
            return None
        if isinstance(value, str):
            name = value
        else:
            name = value.name
        request = self.context.get("request")
        return reverse(
            "analysis:workflow-detail",
            kwargs={"name": name},
            request=request,
        )

    def to_internal_value(self, data):
        try:
            workflow = resolve_workflow(str(data))
        except ValueError as e:
            raise serializers.ValidationError(str(e))
        # Return the name string so it can be stored in the CharField
        return workflow.name
