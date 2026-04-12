from django.contrib import admin
from .models import Vendor, VendorEarning, AppCommission


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display   = ('shop_name', 'owner', 'status', 'commission_rate', 'joined_at')
    list_filter    = ('status',)
    search_fields  = ('shop_name', 'owner__phone', 'owner__first_name')
    readonly_fields = ('joined_at', 'approved_at', 'slug')
    actions        = ['approve_vendors', 'suspend_vendors']

    def approve_vendors(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='active', approved_at=timezone.now())
        self.message_user(request, f'{queryset.count()} vendor(s) approved.')
    approve_vendors.short_description = 'Approve selected vendors'

    def suspend_vendors(self, request, queryset):
        queryset.update(status='suspended')
        self.message_user(request, f'{queryset.count()} vendor(s) suspended.')
    suspend_vendors.short_description = 'Suspend selected vendors'


@admin.register(VendorEarning)
class VendorEarningAdmin(admin.ModelAdmin):
    list_display  = ('vendor', 'order', 'gross_amount', 'commission', 'net_amount', 'status')
    list_filter   = ('status',)
    search_fields = ('vendor__shop_name', 'order__order_ref')


@admin.register(AppCommission)
class AppCommissionAdmin(admin.ModelAdmin):
    list_display  = ('vendor', 'order', 'amount', 'rate', 'created_at')
    search_fields = ('vendor__shop_name', 'order__order_ref')