# rider/ledger_service.py
"""
Called after a delivery is marked as 'delivered' and customer paid the
rider directly. Records the commission split and updates the rider's balance.
"""
import logging
from decimal import Decimal

log = logging.getLogger(__name__)


def record_delivery_commission(delivery, payment_method='cash'):
    """
    Create a RiderLedgerEntry for a completed delivery.
    Called from: rider/views.py → update_delivery() when status = 'delivered'

    Args:
        delivery      : Delivery instance (must have rider and delivery_fee set)
        payment_method: 'cash' or 'momo' (how customer paid rider)
    """
    from rider.models import RiderLedgerEntry, RiderBalanceSummary
    from django.utils import timezone

    rider_profile = delivery.rider
    if not rider_profile:
        log.warning("record_delivery_commission: no rider on delivery %s", delivery.pk)
        return None

    # Avoid duplicate entries
    if hasattr(delivery, 'ledger_entry'):
        return delivery.ledger_entry

    gross = Decimal(str(delivery.delivery_fee or 0))
    if gross <= 0:
        return None

    # App's commission percentage = 100 - rider's commission_rate
    rider_pct = Decimal(str(rider_profile.commission_rate))  # e.g. 95.00
    app_pct   = Decimal('100') - rider_pct                   # e.g.  5.00

    rider_net      = (gross * rider_pct / Decimal('100')).quantize(Decimal('0.01'))
    app_commission = (gross * app_pct   / Decimal('100')).quantize(Decimal('0.01'))

    entry = RiderLedgerEntry.objects.create(
        rider          = rider_profile,
        delivery       = delivery,
        gross_amount   = gross,
        rider_net      = rider_net,
        app_commission = app_commission,
        commission_pct = app_pct,
        payment_method = payment_method,
        is_settled     = False,
    )
    log.info("Ledger entry: rider=%s gross=%.2f app_cut=%.2f",
             rider_profile, gross, app_commission)

    # Update running balance
    balance, _ = RiderBalanceSummary.objects.get_or_create(rider=rider_profile)
    balance.total_earned  = balance.total_earned  + gross
    balance.total_app_cut = balance.total_app_cut + app_commission
    balance.outstanding   = balance.outstanding   + app_commission
    balance.save(update_fields=['total_earned', 'total_app_cut', 'outstanding', 'updated_at'])

    # Notify admin if outstanding balance exceeds threshold
    _notify_admin_if_threshold(rider_profile, balance)

    return entry


def settle_entry(entry, settled_by_user, note=''):
    """Mark a ledger entry as settled (admin confirms rider paid the app)."""
    from rider.models import RiderBalanceSummary
    from django.utils import timezone

    if entry.is_settled:
        return entry

    entry.is_settled      = True
    entry.settled_at      = timezone.now()
    entry.settled_by      = settled_by_user
    entry.settlement_note = note
    entry.save()

    # Update balance
    balance = entry.rider.balance
    balance.total_settled = balance.total_settled + entry.app_commission
    balance.outstanding   = balance.outstanding   - entry.app_commission
    balance.save(update_fields=['total_settled', 'outstanding', 'updated_at'])

    return entry


def settle_all_for_rider(rider_profile, settled_by_user, note=''):
    """Settle ALL outstanding entries for a rider at once."""
    from rider.models import RiderLedgerEntry

    unsettled = RiderLedgerEntry.objects.filter(
        rider=rider_profile, is_settled=False
    )
    count = 0
    for entry in unsettled:
        settle_entry(entry, settled_by_user, note)
        count += 1
    return count


def _notify_admin_if_threshold(rider_profile, balance, threshold=50):
    """Notify admin when a rider's outstanding balance exceeds threshold."""
    if float(balance.outstanding) < threshold:
        return
    try:
        from rider.admin_notify import notify_admins_new_rider
        from django.contrib.auth import get_user_model
        User = get_user_model()
        from rider.notification_model import RiderNotification
        name = rider_profile.rider.get_full_name() or str(rider_profile.rider.phone)
        admins = User.objects.filter(role__in=['admin', 'staff'], is_active=True)
        for admin in admins:
            RiderNotification.objects.get_or_create(
                rider      = admin,
                title      = f'💰 Rider Balance Alert — {name}',
                message    = (f'{name} owes GHS {balance.outstanding:.2f} to the app. '
                              f'Collect payment.'),
                link       = '/rider/admin/balances/',
                notif_type = 'payment',
            )
    except Exception:
        pass