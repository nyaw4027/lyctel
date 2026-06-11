# ecommerce/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display  = ('phone', 'first_name', 'last_name', 'email', 'role',
                     'is_active', 'is_verified', 'created_at')
    list_filter   = ('role', 'is_active', 'is_verified', 'is_staff')
    search_fields = ('phone', 'first_name', 'last_name', 'email')
    ordering      = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at', 'last_seen', 'uuid')

    fieldsets = (
        (None, {
            'fields': ('phone', 'username', 'password')
        }),
        (_('Personal Info'), {
            'fields': ('first_name', 'last_name', 'email', 'profile_pic',
                       'date_of_birth', 'bio', 'address', 'city', 'region', 'country')
        }),
        (_('Role & Status'), {
            'fields': ('role', 'is_active', 'is_verified',
                       'is_phone_verified', 'is_email_verified')
        }),
        (_('Permissions'), {
            'fields': ('is_staff', 'is_superuser', 'groups', 'user_permissions'),
            'classes': ('collapse',),
        }),
        (_('Important Dates'), {
            'fields': ('last_login', 'created_at', 'updated_at', 'last_seen'),
        }),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('phone', 'first_name', 'last_name',
                       'role', 'password1', 'password2'),
        }),
    )