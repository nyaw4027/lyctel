# ── products/admin.py — add this to make flash sales editable in Django admin ──
# Paste into your existing products/admin.py, replacing or updating ProductAdmin

from django.contrib import admin
from .models import Product, ProductImage, ProductVideo, Category

class ProductImageInline(admin.TabularInline):
    model  = ProductImage
    extra  = 1
    fields = ['image', 'is_primary', 'order']

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display   = ['name', 'vendor', 'selling_price', 'flash_price',
                      'flash_sale_ends', 'is_flash_sale_active', 'status', 'stock_qty']
    list_editable  = ['flash_price', 'flash_sale_ends', 'status', 'stock_qty']
    list_filter    = ['status', 'category', 'is_featured', 'vendor']
    search_fields  = ['name', 'sku', 'vendor__shop_name']
    readonly_fields= ['is_flash_sale_active', 'flash_seconds_remaining',
                      'effective_price', 'created_at', 'updated_at']
    inlines        = [ProductImageInline]

    fieldsets = (
        ('Basic Info',   {'fields': ('vendor','name','slug','category','description',
                                     'short_description','brand','status')}),
        ('Pricing',      {'fields': ('cost_price','selling_price','discount_price',
                                     'flash_price','flash_sale_ends',
                                     'is_flash_sale_active','effective_price')}),
        ('Inventory',    {'fields': ('sku','stock_qty','low_stock_alert','weight')}),
        ('Flags',        {'fields': ('is_featured','is_digital')}),
        ('Timestamps',   {'fields': ('created_at','updated_at'), 'classes': ('collapse',)}),
    )

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display  = ['name', 'parent', 'category_type', 'is_active', 'sort_order']
    list_editable = ['is_active', 'sort_order']
    prepopulated_fields = {'slug': ('name',)}