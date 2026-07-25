from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsStaffUser(BasePermission):
    """
    Grant read access to staff users only.

    ``is_staff`` is the same flag that gates the Django admin, so anybody who
    can open the admin can open the dashboards, and nobody else can.
    """

    message = "Only staff users may access the staff dashboards."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and user.is_staff
            and request.method in SAFE_METHODS
        )
