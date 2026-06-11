from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):

    # ── List view ─────────────────────────────────────────
    list_display  = (
        'avatar_tag', 'phone', 'full_name_display',
        'email', 'role_badge', 'is_active', 'is_verified',
        'created_at',
    )
    list_display_links = ('phone', 'full_name_display')
    list_filter   = ('role', 'is_active', 'is_verified', 'is_phone_verified', 'country')
    search_fields = ('phone', 'first_name', 'last_name', 'email', 'username')
    ordering      = ('-created_at',)
    list_per_page = 25
    date_hierarchy = 'created_at'

    # ── Actions ───────────────────────────────────────────
    actions = ['activate_users', 'deactivate_users', 'verify_users']

    def activate_users(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f'{queryset.count()} user(s) activated.')
    activate_users.short_description = '✅ Activate selected users'

    def deactivate_users(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f'{queryset.count()} user(s) deactivated.')
    deactivate_users.short_description = '🚫 Deactivate selected users'

    def verify_users(self, request, queryset):
        queryset.update(is_verified=True)
        self.message_user(request, f'{queryset.count()} user(s) marked as verified.')
    verify_users.short_description = '🔒 Mark selected users as verified'

    # ── Custom columns ────────────────────────────────────
    @admin.display(description='')
    def avatar_tag(self, obj):
        if obj.profile_pic:
            return format_html(
                '<img src="{}" style="width:32px;height:32px;border-radius:50%;object-fit:cover;"/>',
                obj.profile_pic.url
            )
        initials = (
            (obj.first_name[:1] if obj.first_name else '') +
            (obj.last_name[:1]  if obj.last_name  else '')
        ).upper() or '?'
        return format_html(
            '<div style="width:32px;height:32px;border-radius:50%;background:#0F1B2D;'
            'color:white;display:flex;align-items:center;justify-content:center;'
            'font-size:12px;font-weight:700;">{}</div>',
            initials
        )

    @admin.display(description='Name')
    def full_name_display(self, obj):
        return obj.get_full_name() or '—'

    @admin.display(description='Role')
    def role_badge(self, obj):
        colours = {
            'admin':    '#0F1B2D',
            'staff':    '#2563eb',
            'vendor':   '#7c3aed',
            'rider':    '#d97706',
            'customer': '#16a34a',
        }
        bg = colours.get(obj.role, '#6b7280')
        return format_html(
            '<span style="background:{};color:white;padding:2px 10px;'
            'border-radius:12px;font-size:11px;font-weight:600;">{}</span>',
            bg, obj.get_role_display()
        )

    # ── Detail view fieldsets ─────────────────────────────
    fieldsets = (
        ('Login Credentials', {
            'fields': ('phone', 'username', 'email', 'password')
        }),
        ('Personal Info', {
            'fields': ('first_name', 'last_name', 'profile_pic',
                       'date_of_birth', 'bio')
        }),
        ('Role & Permissions', {
            'fields': ('role', 'is_active', 'is_staff', 'is_superuser',
                       'groups', 'user_permissions')
        }),
        ('Verification', {
            'fields': ('is_verified', 'is_phone_verified', 'is_email_verified')
        }),
        ('Location', {
            'fields': ('address', 'city', 'region', 'country'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_seen', 'last_login'),
            'classes': ('collapse',),
        }),
    )

    add_fieldsets = (
        ('Create User', {
            'classes': ('wide',),
            'fields': (
                'phone', 'username', 'first_name', 'last_name',
                'email', 'role', 'password1', 'password2',
            ),
        }),
    )

    readonly_fields = ('created_at', 'updated_at', 'last_seen', 'last_login', 'uuid')