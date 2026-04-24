from django.contrib import admin
from .models import Product, Category, ProductImage


# ─────────────────────────────
# CATEGORY ADMIN
# ─────────────────────────────
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)
    list_filter = ("is_active",)


# ─────────────────────────────
# PRODUCT ADMIN
# ─────────────────────────────
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "selling_price",
        "discount_price",
        "discount_percent_display",
        "stock_qty",
        "status",
        "is_featured",
        "is_hot_deal",
    )

    list_filter = (
        "status",
        "is_featured",
        "category",
        "stock_qty",
    )

    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("-created_at",)

    readonly_fields = ("created_at", "updated_at", "discount_percent_display")

    # ───── HOT DEAL FILTER (ADMIN ONLY LOGIC) ─────
    def is_hot_deal(self, obj):
        return obj.has_discount and obj.discount_percent >= 10
    is_hot_deal.boolean = True
    is_hot_deal.short_description = "🔥 Hot Deal"


    def discount_percent_display(self, obj):
        return f"{obj.discount_percent}%"
    discount_percent_display.short_description = "Discount %"


# ─────────────────────────────
# PRODUCT IMAGE ADMIN
# ─────────────────────────────
@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("product", "is_primary", "order")
    list_filter = ("is_primary",)
    search_fields = ("product__name",)