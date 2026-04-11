from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display  = ('phone', 'first_name', 'last_name', 'role', 'is_active')
    list_filter   = ('role', 'is_active')
    search_fields = ('phone', 'first_name', 'last_name', 'email')
    ordering      = ('-created_at',)

    fieldsets = UserAdmin.fieldsets + (
        ('Role & Profile', {'fields': ('role', 'phone', 'address', 'profile_pic')}),
    )