# ============================================================
# ecommerce/context_processors.py
# Makes RBAC data available in every Django template
# ============================================================
from .rbac import get_user_permissions, get_role_label, get_role_icon, has_permission, ROLES


def rbac_context(request):
    """
    Add to settings.py TEMPLATES[0]['OPTIONS']['context_processors']:
        'ecommerce.context_processors.rbac_context',

    Then in any template:
        {% if can.manage_products %}  ... {% endif %}
        {% if user_role == 'admin' %} ... {% endif %}
        {{ role_label }}  →  "Admin"
        {{ role_icon }}   →  "⚡"
    """
    if not request.user.is_authenticated:
        return {
            'user_role':        None,
            'role_label':       None,
            'role_icon':        '👤',
            'user_permissions': set(),
            'can':              _PermissionProxy(set()),
            'all_roles':        ROLES,
        }

    perms = set(get_user_permissions(request.user))
    role  = getattr(request.user, 'role', 'customer')

    return {
        'user_role':        role,
        'role_label':       get_role_label(role),
        'role_icon':        get_role_icon(role),
        'user_permissions': perms,
        'can':              _PermissionProxy(perms),
        'all_roles':        ROLES,
    }


class _PermissionProxy:
    """
    Allows template syntax like:  {% if can.manage_products %}
    Instead of the verbose:       {% if 'manage_products' in user_permissions %}
    """
    def __init__(self, permissions: set):
        self._perms = permissions

    def __getattr__(self, name):
        return name in self._perms

    def __contains__(self, item):
        return item in self._perms