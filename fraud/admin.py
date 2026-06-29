from django.contrib import admin
from django.utils import timezone

from .models import FraudFlag, PaymentAttempt
from .services import release_vendor_payout


@admin.action(description='Clear selected flags (false positive — release payout if nothing else blocks it)')
def clear_flags(modeladmin, request, queryset):
    queryset.update(resolved=True, is_confirmed_fraud=False, resolved_by=request.user, resolved_at=timezone.now())

    # Re-check each affected order individually — bulk-clearing flag A on
    # an order doesn't mean flag B on the SAME order is also clear.
    orders = {flag.order for flag in queryset.select_related('order')}
    for order in orders:
        other_unresolved     = FraudFlag.objects.filter(order=order, resolved=False).exists()
        ever_confirmed_fraud = FraudFlag.objects.filter(order=order, is_confirmed_fraud=True).exists()
        if not other_unresolved and not ever_confirmed_fraud:
            release_vendor_payout(order)


@admin.action(description='Confirm selected flags as REAL fraud (payout stays held permanently)')
def confirm_fraud_flags(modeladmin, request, queryset):
    queryset.update(resolved=True, is_confirmed_fraud=True, resolved_by=request.user, resolved_at=timezone.now())


@admin.register(FraudFlag)
class FraudFlagAdmin(admin.ModelAdmin):
    list_display    = ('order', 'flag_type', 'severity', 'resolved', 'is_confirmed_fraud', 'created_at')
    list_filter     = ('flag_type', 'severity', 'resolved', 'is_confirmed_fraud')
    search_fields   = ('order__order_ref', 'reason')
    actions         = [clear_flags, confirm_fraud_flags]
    readonly_fields = ('order', 'flag_type', 'severity', 'reason', 'created_at')


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(admin.ModelAdmin):
    list_display    = ('customer', 'order', 'success', 'ip_address', 'created_at')
    list_filter     = ('success',)
    search_fields   = ('customer__phone', 'order__order_ref', 'ip_address')
    readonly_fields = [f.name for f in PaymentAttempt._meta.fields]