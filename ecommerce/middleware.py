# ============================================================
# ecommerce/middleware.py
# RBAC Middleware — attaches permissions to every request
# ============================================================
from .rbac import get_user_permissions, get_role_label, get_role_icon, ROLES


class RBACMiddleware:
    """
    Attaches role info and permissions to every request object.
    Access in any view as: request.user_permissions, request.user_role
    Access in any template via context processor below.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            request.user_role        = getattr(request.user, 'role', 'customer')
            request.user_permissions = set(get_user_permissions(request.user))
            request.role_label       = get_role_label(request.user_role)
            request.role_icon        = get_role_icon(request.user_role)
        else:
            request.user_role        = None
            request.user_permissions = set()
            request.role_label       = None
            request.role_icon        = None

        return self.get_response(request)