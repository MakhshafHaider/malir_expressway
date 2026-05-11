from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.user_role == 'admin'


class IsOperator(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.user_role in ('admin', 'operator')


class IsOwnerOrAdmin(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.user.user_role == 'admin':
            return True
        return getattr(obj, 'owner', None) == request.user
