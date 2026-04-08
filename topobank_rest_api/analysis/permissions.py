from rest_framework.permissions import BasePermission


class WorkflowPermissions(BasePermission):
    def has_object_permission(self, request, view, obj):
        # Workflows no longer have permissions (all users can view them),
        # but WorkflowResults still do.
        if hasattr(obj, 'has_permission'):
            return obj.has_permission(request.user)
        return True
