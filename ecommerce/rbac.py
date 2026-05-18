# ============================================================
# ecommerce/rbac.py
# Complete Role-Based Access Control for Lynctel
# ============================================================
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.http import JsonResponse
from django.core.exceptions import PermissionDenied


# ── ROLE DEFINITIONS ─────────────────────────────────────
ROLES = {
    'customer': {
        'label': 'Customer',
        'icon':  '🛍️',
        'permissions': [
            'view_products',
            'add_to_cart',
            'place_order',
            'view_own_orders',
            'track_order',
            'write_review',
            'view_own_profile',
            'edit_own_profile',
            'apply_as_vendor',
        ],
    },
    'vendor': {
        'label': 'Vendor',
        'icon':  '🏪',
        'permissions': [
            # inherits all customer permissions
            'view_products',
            'view_own_orders',
            'view_own_profile',
            'edit_own_profile',
            # vendor-specific
            'manage_own_products',
            'view_own_shop_orders',
            'view_own_earnings',
            'edit_own_shop_settings',
        ],
    },
    'rider': {
        'label': 'Rider',
        'icon':  '🛵',
        'permissions': [
            'view_products',
            'view_own_profile',
            'edit_own_profile',
            # rider-specific
            'view_assigned_deliveries',
            'accept_delivery',
            'reject_delivery',
            'update_delivery_status',
            'view_own_earnings',
        ],
    },
    'staff': {
        'label': 'Staff',
        'icon':  '👔',
        'permissions': [
            # everything except finance and user management
            'view_products',
            'manage_products',
            'view_all_orders',
            'update_order_status',
            'view_all_customers',
            'view_vendors',
            'approve_vendors',
            'view_riders',
            'assign_riders',
            'view_deliveries',
            'view_staff',
        ],
    },
    'admin': {
        'label': 'Admin',
        'icon':  '⚡',
        'permissions': '__all__',   # admin gets everything
    },
}

# All possible permissions in the system
ALL_PERMISSIONS = set()
for role_data in ROLES.values():
    if role_data['permissions'] != '__all__':
        ALL_PERMISSIONS.update(role_data['permissions'])


# ── PERMISSION CHECK ──────────────────────────────────────

def has_permission(user, permission):
    """Check if a user has a specific permission based on their role."""
    if not user or not user.is_authenticated:
        return False

    role = getattr(user, 'role', 'customer')
    role_data = ROLES.get(role, ROLES['customer'])

    if role_data['permissions'] == '__all__':
        return True

    return permission in role_data['permissions']


def has_any_permission(user, *permissions):
    return any(has_permission(user, p) for p in permissions)


def has_all_permissions(user, *permissions):
    return all(has_permission(user, p) for p in permissions)


def get_user_permissions(user):
    """Return list of all permissions for a user."""
    if not user or not user.is_authenticated:
        return []
    role = getattr(user, 'role', 'customer')
    role_data = ROLES.get(role, ROLES['customer'])
    if role_data['permissions'] == '__all__':
        return list(ALL_PERMISSIONS)
    return list(role_data['permissions'])


def get_role_label(role):
    return ROLES.get(role, {}).get('label', role.title())


def get_role_icon(role):
    return ROLES.get(role, {}).get('icon', '👤')


# ── DECORATORS ────────────────────────────────────────────

def require_permission(permission, redirect_url=None):
    """
    Decorator that checks if the logged-in user has a specific permission.

    Usage:
        @require_permission('manage_products')
        def my_view(request): ...

        @require_permission('view_all_orders', redirect_url='/dashboard/')
        def admin_view(request): ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f'/accounts/login/?next={request.path}')

            if not has_permission(request.user, permission):
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse(
                        {'error': 'You do not have permission to perform this action.'},
                        status=403
                    )
                messages.error(request, 'You do not have permission to access that page.')
                target = redirect_url or _default_redirect(request.user)
                return redirect(target)

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def require_role(*roles):
    """
    Decorator that checks if user has one of the specified roles.

    Usage:
        @require_role('admin', 'staff')
        def admin_view(request): ...

        @require_role('vendor')
        def vendor_view(request): ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f'/accounts/login/?next={request.path}')

            user_role = getattr(request.user, 'role', 'customer')
            if user_role not in roles:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse(
                        {'error': f'Access restricted to: {", ".join(roles)}'},
                        status=403
                    )
                messages.error(request, f'This area is restricted to {" and ".join(r.title() for r in roles)}s.')
                return redirect(_default_redirect(request.user))

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def login_required_rbac(view_func):
    """Simple login check with smart redirect."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/accounts/login/?next={request.path}')
        return view_func(request, *args, **kwargs)
    return wrapper


def _default_redirect(user):
    """Send user to the right place based on their role."""
    role = getattr(user, 'role', 'customer')
    redirects = {
        'admin':    '/dashboard/',
        'staff':    '/dashboard/',
        'vendor':   '/vendor/dashboard/',
        'rider':    '/rider/',
        'customer': '/',
    }
    return redirects.get(role, '/')


# ── ACTIVE VENDOR GUARD ───────────────────────────────────

def vendor_required(view_func):
    """
    Guard for vendor views.
    User must be authenticated AND have an active vendor account.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/accounts/login/?next={request.path}')

        try:
            vendor = request.user.vendor
            if vendor.status == 'active':
                request.vendor = vendor
                return view_func(request, *args, **kwargs)
            elif vendor.status == 'pending':
                messages.warning(request, 'Your vendor account is awaiting approval.')
                return redirect('/vendor/pending/')
            else:
                messages.error(request, 'Your vendor account has been suspended.')
                return redirect('/')
        except Exception:
            messages.info(request, 'Apply to become a vendor first.')
            return redirect('/vendor/apply/')

    return wrapper


# ── RIDER GUARD ───────────────────────────────────────────

def rider_required(view_func):
    """Guard for rider views."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/accounts/login/?next={request.path}')

        if not has_permission(request.user, 'view_assigned_deliveries'):
            messages.error(request, 'Access denied. Rider accounts only.')
            return redirect('/')

        try:
            request.rider_profile = request.user.rider_profile
        except Exception:
            messages.error(request, 'Rider profile not found. Contact admin.')
            return redirect('/')

        return view_func(request, *args, **kwargs)
    return wrapper


# ── ADMIN / STAFF GUARD ───────────────────────────────────

def admin_required(view_func):
    """Guard for admin dashboard views."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/accounts/login/?next={request.path}')

        role = getattr(request.user, 'role', 'customer')
        if role not in ('admin', 'staff'):
            messages.error(request, 'Access denied. Admin accounts only.')
            return redirect('/')

        return view_func(request, *args, **kwargs)
    return wrapper


def staff_permission_required(permission):
    """
    Guard for specific admin actions that should be
    restricted even within staff (e.g. only admin can delete users).
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f'/accounts/login/?next={request.path}')

            if not has_permission(request.user, permission):
                messages.error(request, 'You do not have permission for this action.')
                return redirect('/dashboard/')

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator