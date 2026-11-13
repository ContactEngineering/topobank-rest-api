from rest_framework.permissions import SAFE_METHODS, BasePermission


class UserPermission(BasePermission):
    """
    Handle permissions for accessing users.
    * Staff users can do everything
    * Users can see the users they share a group or a dataset with
      (enforced by `UserViewSet.get_queryset`)
    * Users can only edit themselves
    """

    def has_permission(self, request, view):
        if not request.user or request.user.is_anonymous:
            return False

        if request.user.is_staff:
            return True
        else:
            return request.method in ("PATCH", "PUT", *SAFE_METHODS)

    def has_object_permission(self, request, view, obj):
        if not request.user or request.user.is_anonymous:
            return False
        # Admin users can do any operation on the users
        elif request.user.is_staff:
            return True
        # SAFE_METHODS are read operations. Which users are visible is decided
        # by `UserViewSet.get_queryset`; a user outside of it is a 404 before
        # this check is reached.
        elif request.method in SAFE_METHODS:
            return True
        # This is a PATCH or PUT operation
        else:
            # Write access is only granted if the user is admin or if the user
            # tries to edit itself (e.g. changing name or email address)
            return obj == request.user
