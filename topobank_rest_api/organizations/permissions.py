from rest_framework.permissions import SAFE_METHODS, BasePermission
from topobank_orcid.organizations.models import Organization


class OrganizationPermission(BasePermission):
    """
    Allows write access only to admin users. Users can only access organizations which
    they are members of.
    """

    def has_permission(self, request, view):
        if not request.user or request.user.is_anonymous:
            return False

        if request.user.is_staff or request.method in SAFE_METHODS:
            return True

        return False

    def has_object_permission(self, request, view, obj):
        if not request.user or request.user.is_anonymous:
            return False

        if request.user.is_staff:
            return True

        if request.method in SAFE_METHODS:
            return obj in Organization.objects.for_user(request.user)

        return False
