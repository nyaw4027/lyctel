from django.contrib import admin
from .models import DeliveryZone, Delivery


# ─────────────────────────────
# DELIVERY ZONE ADMIN
# ─────────────────────────────
@admin.register(DeliveryZone)
class DeliveryZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "delivery_fee", "estimated_days", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    ordering = ("name",)


# ─────────────────────────────
# DELIVERY ADMIN
# ─────────────────────────────
@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "order",
        "rider",
        "zone",
        "status",
        "delivery_fee",
        "rider_commission",
        "assigned_at",
    )

    list_filter = ("status", "zone", "assigned_at")
    search_fields = ("order__order_ref", "rider__user__username")
    ordering = ("-assigned_at",)

    readonly_fields = (
        "assigned_at",
        "picked_up_at",
        "delivered_at",
        "rider_commission",
    )

    fieldsets = (
        ("Order Info", {
            "fields": ("order", "zone")
        }),

        ("Rider Assignment", {
            "fields": ("rider", "status")
        }),

        ("Financials", {
            "fields": ("delivery_fee", "rider_commission")
        }),

        ("Tracking", {
            "fields": ("assigned_at", "picked_up_at", "delivered_at")
        }),

        ("Extras", {
            "fields": ("proof_of_delivery", "delivery_note")
        }),
    )

    # 🔥 ACTION: mark as delivered
    actions = ["mark_as_delivered"]

    def mark_as_delivered(self, request, queryset):
        queryset.update(status="delivered")
    mark_as_delivered.short_description = "Mark selected deliveries as Delivered"