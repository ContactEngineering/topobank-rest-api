from allauth.account.utils import has_verified_email
from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from topobank_rest_api.supplib.mixins import StrictFieldMixin


class UserSerializer(StrictFieldMixin, serializers.HyperlinkedModelSerializer):
    """Serializer for User model."""
    class Meta:
        model = get_user_model()
        fields = [
            # Self
            "url",
            "id",
            # Auxiliary API endpoints
            "api",
            # Model fields
            "name",
            "username",
            "orcid",
            "email",
            "date_joined",
            # Auth fields
            "is_verified",
            "is_staff",
        ]
        read_only_fields = ["id", "date_joined", "is_verified", "is_staff"]

    url = serializers.HyperlinkedIdentityField(
        view_name="users:user-v1-detail", read_only=True
    )
    api = serializers.SerializerMethodField()
    orcid = serializers.SerializerMethodField()
    is_verified = serializers.SerializerMethodField()

    @extend_schema_field(
        {
            "type": "object",
            "properties": {},
        }
    )
    def get_api(self, obj) -> dict:
        return {}

    def get_orcid(self, obj) -> str:
        try:
            return obj.orcid_id
        except Exception:
            return None

    def get_is_verified(self, obj) -> bool:
        return has_verified_email(obj)
