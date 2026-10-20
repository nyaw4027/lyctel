# rider/ledger_service.py
"""
Records the commission split for a completed delivery and keeps the rider's
running balance. Called from rider/views.py -> update_delivery() on 'delivered'.

CHANGES (audit):
  * Rate is now the platform's 10% delivery commission (ecommerce/commission.py).
    It used to read RiderProfile.commission_rate, whose default is 50 — so every
    rider was being credited only 50% of the fee.
  * settle_entry / settle_all_for_rider imported from `rider.ledger_models`,
    a module that does not exist (the models live in rider.models) -> ImportError
    the first time an admin tried to settle. Fixed.
  * Entry + balance update are one atomic transaction (a crash between the two
    used to leave the balance out of step with the ledger), and the balance row
    is updated with F() so two deliveries finishing together can't overwrite
    each other.
"""
import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import F

log = logging.getLogger(__name__)


def record_delivery_commission(delivery, payment_method='cash'):
    from rider.models import RiderLedgerEntry, RiderBalanceSummary
    from ecommerce.commission import split_delivery_fee

    rider_profile = delivery.rider
    if not rider_profile:
        log.warning("record_delivery_commission: no rider on delivery %s", delivery.pk)
        return None

    split = split_delivery_fee(delivery.delivery_fee)
    if split['gross'] <= 0:
        return None

    with transaction.atomic():
        entry, created = RiderLedgerEntry.objects.get_or_create(
            delivery=delivery,                      # OneToOne -> idempotent
            defaults=dict(
                rider          = rider_profile,
                gross_amount   = split['gross'],
                rider_net      = split['payee'],
                app_commission = split['app'],
                commission_pct = split['app_pct'],
                payment_method = payment_method,
                is_settled     = False,
            ),
        )
        if not created:
            return entry

        RiderBalanceSummary.objects.get_or_create(rider=rider_profile)
        RiderBalanceSummary.objects.filter(rider=rider_profile).update(
            total_earned  = F('total_earned')  + split['gross'],
            total_app_cut = F('total_app_cut') + split['app'],
            outstanding   = F('outstanding')   + split['app'],
        )
        balance = RiderBalanceSummary.objects.get(rider=rider_profile)

    log.info("Ledger entry: rider=%s gross=%s rider_net=%s app_cut=%s",
             rider_profile, split['gross'], split['payee'], split['app'])
    _notify_admin_if_threshold(rider_profile, balance)
    return entry


def settle_entry(entry, settled_by_user, note=''):
    """Admin confirms the rider has paid the app its commission for this entry."""
    from rider.models import RiderBalanceSummary, RiderLedgerEntry
    from django.utils import timezone

    with transaction.atomic():
        entry = RiderLedgerEntry.objects.select_for_update().get(pk=entry.pk)
        if entry.is_settled:
            return entry
        entry.is_settled      = True
        entry.settled_at      = timezone.now()
        entry.settled_by      = settled_by_user
        entry.settlement_note = note
        entry.save()
        RiderBalanceSummary.objects.filter(rider=entry.rider).update(
            total_settled = F('total_settled') + entry.app_commission,
            outstanding   = F('outstanding')   - entry.app_commission,
        )
    return entry


def settle_all_for_rider(rider_profile, settled_by_user, note=''):
    from rider.models import RiderLedgerEntry
    count = 0
    for entry in RiderLedgerEntry.objects.filter(rider=rider_profile, is_settled=False):
        settle_entry(entry, settled_by_user, note)
        count += 1
    return count


def _notify_admin_if_threshold(rider_profile, balance, threshold=50):
    if float(balance.outstanding) < threshold:
        return
    try:
        from django.contrib.auth import get_user_model
        from rider.notification_model import RiderNotification
        User = get_user_model()
        name = rider_profile.rider.get_full_name() or str(rider_profile.rider.phone)
        for admin in User.objects.filter(role__in=['admin', 'staff'], is_active=True):
            RiderNotification.objects.get_or_create(
                rider      = admin,
                title      = f'💰 Rider Balance Alert — {name}',
                message    = f'{name} owes GHS {balance.outstanding:.2f} to the app. Collect payment.',
                link       = '/rider/admin/balances/',
                notif_type = 'payment',
            )
    except Exception:
        log.exception('rider balance alert failed')