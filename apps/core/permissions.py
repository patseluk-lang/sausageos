from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import Role


class RoleBasedPermission(BasePermission):
    """Role-based access.

    read_roles  — who may read (empty set = any authenticated user).
    write_roles — who may create or modify.
    """

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser or user.role == Role.ADMIN:
            return True
        roles = (
            getattr(view, "read_roles", None)
            if request.method in SAFE_METHODS
            else getattr(view, "write_roles", None)
        )
        if not roles:
            return request.method in SAFE_METHODS
        return user.role in roles
