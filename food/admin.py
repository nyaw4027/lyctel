from django.contrib import admin
from django.utils.html import format_html
from .models import (
    FoodVendor, FoodCategory, FoodItem,
    FoodOrder, FoodOrderItem, FoodCart, FoodCartItem,
)


class FoodCategoryInline(admin.TabularInline):
    model = FoodCategory
    extra = 1


class FoodItemInline(admin.TabularInline):
    model   = FoodItem
    extra   = 1
    fields  = ('name', 'category', 'price', 'is_available', 'is_featured')


@admin.register(FoodVendor)
class FoodVendorAdmin(admin.ModelAdmin):
    list_display  = ('name', 'cuisine', 'status_badge', 'city', 'avg_prep_time',
                     'total_orders', 'rating', 'is_featured')
    list_filter   = ('status', 'cuisine', 'city', 'is_featured')
    search_fields = ('name', 'address', 'phone')
    prepopulated_fields = {'slug': ('name',)}
    inlines       = [FoodCategoryInline, FoodItemInline]
    actions       = ['mark_open', 'mark_closed']

    @admin.display(description='Status')
    def status_badge(self, obj):
        colours = {
            'open':      '#16a34a',
            'closed':    '#6b7280',
            'busy':      '#d97706',
            'suspended': '#dc2626',
        }
        bg = colours.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background:{};color:white;padding:2px 10px;'
            'border-radius:12px;font-size:11px;font-weight:600;">{}</span>',
            bg, obj.get_status_display(),
        )

    @admin.action(description='Mark selected as Open')
    def mark_open(self, request, queryset):
        queryset.update(status=FoodVendor.Status.OPEN)

    @admin.action(description='Mark selected as Closed')
    def mark_closed(self, request, queryset):
        queryset.update(status=FoodVendor.Status.CLOSED)


@admin.register(FoodItem)
class FoodItemAdmin(admin.ModelAdmin):
    list_display  = ('name', 'vendor', 'category', 'price',
                     'is_available', 'is_featured', 'is_spicy')
    list_filter   = ('vendor', 'is_available', 'is_featured', 'is_spicy', 'is_vegan')
    search_fields = ('name', 'vendor__name')
    list_editable = ('is_available', 'is_featured')


class FoodOrderItemInline(admin.TabularInline):
    model      = FoodOrderItem
    extra      = 0
    readonly_fields = ('name', 'price', 'quantity', 'subtotal')


@admin.register(FoodOrder)
class FoodOrderAdmin(admin.ModelAdmin):
    list_display  = ('order_ref', 'customer', 'vendor', 'status_badge',
                     'payment_method', 'total_amount', 'created_at')
    list_filter   = ('status', 'payment_method', 'payment_status')
    search_fields = ('order_ref', 'customer__phone', 'vendor__name')
    readonly_fields = ('order_ref', 'created_at', 'total_amount')
    inlines       = [FoodOrderItemInline]

    @admin.display(description='Status')
    def status_badge(self, obj):
        colours = {
            'pending':   '#6b7280',
            'confirmed': '#2563eb',
            'preparing': '#d97706',
            'ready':     '#7c3aed',
            'picked_up': '#0891b2',
            'en_route':  '#2563eb',
            'delivered': '#16a34a',
            'cancelled': '#dc2626',
        }
        bg = colours.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background:{};color:white;padding:2px 10px;'
            'border-radius:12px;font-size:11px;font-weight:600;">{}</span>',
            bg, obj.get_status_display(),
        )