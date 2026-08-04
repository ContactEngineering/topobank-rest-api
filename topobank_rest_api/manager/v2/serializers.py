import pydantic
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.reverse import reverse
from tagulous.contrib.drf import TagRelatedManagerField
from topobank.files.models import Manifest
from topobank.manager.models import Surface, Topography
from topobank.manager.zip_model import ZipContainer

from topobank_rest_api.files.v2.serializers import ManifestV2Serializer
from topobank_rest_api.supplib.mixins import StrictFieldMixin
from topobank_rest_api.supplib.serializers import (
    ManifestField,
    ModelRelatedField,
    PermissionsField,
    UserField,
)

from ...properties.serializers import PropertiesField
from ...taskapp.serializers import TaskStateModelSerializer


class TopographyV2Serializer(StrictFieldMixin, TaskStateModelSerializer):
    """v2 Serializer for Topography model."""

    class Meta:
        model = Topography
        read_only_fields = [
            "url",
            "id",
            "api",
            "permissions",
            "created_by",
            "updated_by",
            "owned_by",
            "datafile",
            "squeezed_datafile",
            "thumbnail",
            "deepzoom",
            "datafile_format",
            "channel_names",
            "created_at",
            "updated_at",
            "task_duration",
            "task_error",
            "task_progress",
            "task_state",
            "task_timer",
            "size_editable",
            "unit_editable",
            "height_scale_editable",
            "has_undefined_data",
            "undefined_data_fraction",
            "detrend_parameters",
            "is_periodic_editable",
            "is_metadata_complete",
        ]
        fields = read_only_fields + [
            "surface",
            "data_source",
            "attachments",
            "name",
            "description",
            "measurement_date",
            "size_x",
            "size_y",
            "unit",
            "height_scale",
            "fill_undefined_data_mode",
            "detrend_mode",
            "resolution_x",
            "resolution_y",
            "bandwidth_lower",
            "bandwidth_upper",
            "short_reliability_cutoff",
            "is_periodic",
            "instrument_name",
            "instrument_type",
            "instrument_parameters",
            "tags",
        ]

    # Self
    url = serializers.HyperlinkedIdentityField(
        view_name="manager:topography-v2-detail", read_only=True
    )

    # Hyperlinked resources
    created_by = UserField(read_only=True)
    updated_by = UserField(read_only=True)
    owned_by = serializers.CharField(
        source="owned_by.name", read_only=True, allow_null=True
    )
    surface = ModelRelatedField(
        view_name="manager:surface-v2-detail", queryset=Surface.objects.all()
    )
    datafile = ManifestField(read_only=True)
    squeezed_datafile = ManifestField(read_only=True)
    thumbnail = ManifestField(read_only=True)
    deepzoom = ModelRelatedField(view_name="files:folder-api-detail", read_only=True)
    attachments = ModelRelatedField(view_name="files:folder-api-detail", read_only=True)

    # Auxiliary API endpoints
    api = serializers.SerializerMethodField()

    # Permissions
    permissions = PermissionsField(read_only=True)

    # Everything else
    tags = TagRelatedManagerField(required=False)
    is_metadata_complete = serializers.BooleanField(read_only=True)

    def validate(self, data):
        # Map fields to their editability checks
        editability_checks = {
            "size_x": self.instance.size_editable,
            "size_y": self.instance.size_editable,
            "unit": self.instance.unit_editable,
            "height_scale": self.instance.height_scale_editable,
            "is_periodic": self.instance.is_periodic_editable,
        }

        # Find fields that are in data but not editable
        read_only_fields = [
            field
            for field, is_editable in editability_checks.items()
            if field in data and not is_editable
        ]

        if read_only_fields:
            s = ", ".join([f"`{name}`" for name in read_only_fields])
            raise serializers.ValidationError(
                f"{s} {'is' if len(read_only_fields) == 1 else 'are'} given by the data file and cannot be set"
            )

        return super().validate(data)

    @extend_schema_field(
        {
            "type": "object",
            "properties": {
                "force_inspect": {"type": "string"},
            },
            "required": ["force_inspect"],
        }
    )
    def get_api(self, obj: Topography) -> dict:
        return {
            "force_inspect": reverse(
                "manager:force-inspect",
                kwargs={"pk": obj.id},
                request=self.context["request"],
            ),
        }

    def update(self, instance, validated_data):
        try:
            return super().update(instance, validated_data)
        except pydantic.ValidationError as exc:
            # The kwargs that were provided do not match the function
            raise serializers.ValidationError({"message": str(exc)})


class TopographyV2CreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Topography
        required_fields = [
            "surface",
            "name",
            "datafile",
        ]
        fields = required_fields + ["tags", "description"]

    surface = ModelRelatedField(
        view_name="manager:surface-v2-detail", queryset=Surface.objects.none()
    )
    datafile = ModelRelatedField(
        view_name="files:manifest-v2-detail", queryset=Manifest.objects.none()
    )
    tags = TagRelatedManagerField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")

        if request and hasattr(request, "user"):
            # Limit queryset to surfaces where user has view permission
            # This is the best way to allow drf to validate the permissions and
            # return correct errors automatically.
            self.fields["surface"].queryset = Surface.objects.for_user(request.user)
            self.fields["datafile"].queryset = Manifest.objects.for_user(request.user)

    def create(self, validated_data):
        if "permissions" not in validated_data:
            # Permissions should not be set directly, but inherited from surface
            # But if we are passing them directly we respect that.
            validated_data["permissions"] = validated_data["surface"].permissions
        return super().create(validated_data)

    def to_representation(self, instance):
        return TopographyV2Serializer(instance, context=self.context).data


class TopographySummarySerializer(serializers.ModelSerializer):
    """Lightweight measurement summary embedded in surface responses.

    Carries just enough for a dataset list row — identity, processing state and
    the thumbnail — so that listing surfaces requires no follow-up requests per
    surface. `task_state` is the database field, not the reconciled Celery
    state: a list must not pay a result-backend round trip per measurement.
    """

    class Meta:
        model = Topography
        fields = ["id", "name", "task_state", "thumbnail_url"]

    task_state = serializers.CharField(read_only=True)
    thumbnail_url = serializers.SerializerMethodField()

    def get_thumbnail_url(self, obj: Topography) -> str | None:
        thumbnail = obj.thumbnail
        if thumbnail is None or not thumbnail.file:
            return None
        return thumbnail.file.url


class SurfaceV2Serializer(StrictFieldMixin, serializers.HyperlinkedModelSerializer):
    """v2 Serializer for Surface model."""

    class Meta:
        model = Surface
        read_only_fields = [
            "url",
            "id",
            "api",
            "permissions",
            "created_by",
            "updated_by",
            "owned_by",
            "created_at",
            "updated_at",
            "topographies",
            "sharing_status",
        ]
        fields = read_only_fields + [
            "attachments",
            "name",
            "category",
            "description",
            "tags",
            "properties",
        ]

    # Self
    url = serializers.HyperlinkedIdentityField(
        view_name="manager:surface-v2-detail", read_only=True
    )

    # Auxiliary API endpoints
    api = serializers.SerializerMethodField()

    # Permissions
    permissions = PermissionsField(read_only=True)

    # Hyperlinked resources
    created_by = UserField(read_only=True)
    updated_by = UserField(read_only=True)
    owned_by = serializers.CharField(
        source="owned_by.name", read_only=True, allow_null=True
    )

    attachments = ModelRelatedField(view_name="files:folder-api-detail", read_only=True)

    # Embedded measurement summaries; see `TopographySummarySerializer`
    topographies = TopographySummarySerializer(
        source="topography_set", many=True, read_only=True
    )

    # Everything else
    properties = PropertiesField(required=False)
    tags = TagRelatedManagerField(required=False)
    sharing_status = serializers.SerializerMethodField()

    @extend_schema_field(
        {
            "type": "string",
            "enum": ["own", "shared", "published"],
        }
    )
    def get_sharing_status(self, obj: Surface) -> str:
        # `publication` only exists when the publication plugin is installed;
        # its reverse one-to-one raises an AttributeError-derived exception
        # when the surface is unpublished, which getattr turns into None.
        if getattr(obj, "publication", None) is not None:
            return "published"
        request = self.context["request"]
        if request.user.is_authenticated and obj.created_by_id == request.user.id:
            return "own"
        return "shared"

    @extend_schema_field(
        {
            "type": "object",
            "properties": {
                "async_download": {"type": "string"},
                "topographies": {"type": "string"},
            },
            "required": ["async_download", "topographies"],
        }
    )
    def get_api(self, obj: Surface) -> dict:
        request = self.context["request"]
        return {
            "async_download": reverse(
                "manager:surface-download-v2",
                kwargs={"surface_ids": obj.id},
                request=request,
            ),
            "topographies": reverse("manager:topography-v2-list", request=request)
            + f"?surface={obj.id}",
        }


class ZipContainerV2Serializer(StrictFieldMixin, TaskStateModelSerializer):
    """v2 Serializer for ZipContainer model."""

    class Meta:
        model = ZipContainer
        read_only_fields = [
            "url",
            "id",
            "api",
            "permissions",
            "task_duration",
            "task_error",
            "task_progress",
            "task_state",
            "task_memory",
            "task_traceback",
            "celery_task_state",
            "self_reported_task_state",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        ]
        fields = read_only_fields + [
            "manifest",
        ]

    # Self
    url = serializers.HyperlinkedIdentityField(
        view_name="manager:zip-container-v2-detail", read_only=True
    )

    # Auxiliary API endpoints
    api = serializers.SerializerMethodField()

    # Permissions
    permissions = PermissionsField(read_only=True)

    # Hyperlinked resources
    created_by = UserField(read_only=True)
    updated_by = UserField(read_only=True)

    # The actual file. Serialized in full (rather than with `ManifestField`,
    # which withholds the file URL unless the request carries `?link_file`),
    # because the URL to download the archive from *is* the payload of this
    # endpoint: a client that polls the container has nothing to do with a
    # manifest it cannot fetch.
    manifest = ManifestV2Serializer(read_only=True)

    @extend_schema_field(
        {
            "type": "object",
            "properties": {
                "upload_finished": {"type": "string"},
            },
            "required": ["upload_finished"],
        }
    )
    def get_api(self, obj: ZipContainer) -> dict:
        request = self.context["request"]
        return {
            "upload_finished": reverse(
                "manager:zip-upload-finish-v2",
                kwargs={"pk": obj.id},
                request=request,
            )
        }
