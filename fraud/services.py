"""
Fraud detection rule engine.

Each `check_*` function runs one specific rule and returns True/False
(whether it fired). `run_fraud_checks(order)` is the orchestrator that
runs every rule and, if anything fired, holds the vendor's payout for
that order pending manual review.

All thresholds are configurable via settings.py (with sensible defaults
below) so you can tune sensitivity without touching code:

    FRAUD_ADDRESS_VELOCITY_WINDOW_DAYS = 30
    FRAUD_ADDRESS_VELOCITY_THRESHOLD   = 3   # distinct accounts sharing an address
    FRAUD_CARD_TEST_WINDOW_MINUTES     = 15
    FRAUD_CARD_TEST_FAIL_THRESHOLD     = 3   # failed attempts in the window
    FRAUD_CARD_TEST_DISTINCT_CARDS     = 3   # distinct cards tried in the window
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from order.models import Order
from .models import FraudFlag, PaymentAttempt


# ── INDIVIDUAL RULES ──────────────────────────────────────

def check_address_velocity(order):
    """
    Flags when the SAME delivery address has been used by MULTIPLE
    DIFFERENT customer accounts recently. Classic signal for one person
    running several accounts (promo abuse, stolen-card testing) but
    shipping everything to one real address they control.
    """
    window_days = getattr(settings, 'FRAUD_ADDRESS_VELOCITY_WINDOW_DAYS', 30)
    threshold   = getattr(settings, 'FRAUD_ADDRESS_VELOCITY_THRESHOLD', 3)
    since = timezone.now() - timedelta(days=window_days)

    if not order.delivery_address or not order.delivery_city:
        return False

    other_accounts = (
        Order.objects.filter(
            delivery_address__iexact=order.delivery_address.strip(),
            delivery_city__iexact=order.delivery_city.strip(),
            created_at__gte=since,
        )
        .exclude(customer_id=order.customer_id)
        .values('customer_id')
        .distinct()
    )
    distinct_other_accounts = other_accounts.count()
    total_accounts = distinct_other_accounts + 1  # +1 for this order's own account

    if total_accounts >= threshold:
        _create_flag(
            order=order,
            flag_type=FraudFlag.FlagType.ADDRESS_VELOCITY,
            severity=FraudFlag.Severity.HIGH if total_accounts >= threshold + 2 else FraudFlag.Severity.MEDIUM,
            reason=(
                f'Delivery address "{order.delivery_address}, {order.delivery_city}" has been '
                f'used by {total_accounts} different customer accounts in the last {window_days} days.'
            ),
        )
        return True
    return False


def check_phone_velocity(order):
    """
    Same idea as address velocity, but on delivery_phone instead. Catches
    the case where someone varies the shipping address slightly but reuses
    the same contact number across accounts.
    """
    window_days = getattr(settings, 'FRAUD_ADDRESS_VELOCITY_WINDOW_DAYS', 30)
    threshold   = getattr(settings, 'FRAUD_ADDRESS_VELOCITY_THRESHOLD', 3)
    since = timezone.now() - timedelta(days=window_days)

    if not order.delivery_phone:
        return False

    other_accounts = (
        Order.objects.filter(
            delivery_phone=order.delivery_phone.strip(),
            created_at__gte=since,
        )
        .exclude(customer_id=order.customer_id)
        .values('customer_id')
        .distinct()
    )
    distinct_other_accounts = other_accounts.count()
    total_accounts = distinct_other_accounts + 1

    if total_accounts >= threshold:
        _create_flag(
            order=order,
            flag_type=FraudFlag.FlagType.PHONE_VELOCITY,
            severity=FraudFlag.Severity.HIGH if total_accounts >= threshold + 2 else FraudFlag.Severity.MEDIUM,
            reason=(
                f'Delivery phone "{order.delivery_phone}" has been used by '
                f'{total_accounts} different customer accounts in the last {window_days} days.'
            ),
        )
        return True
    return False


def check_card_testing(customer):
    """
    Flags rapid repeated payment attempts — the classic "card testing"
    pattern where stolen card numbers are run through checkout in quick
    succession to find one that works. Requires PaymentAttempt rows to
    exist, which means your payment app needs to call
    record_payment_attempt() below on every charge attempt (see the
    integration note in that function's docstring).
    """
    if customer is None:
        return False

    window_minutes = getattr(settings, 'FRAUD_CARD_TEST_WINDOW_MINUTES', 15)
    fail_threshold = getattr(settings, 'FRAUD_CARD_TEST_FAIL_THRESHOLD', 3)
    card_threshold = getattr(settings, 'FRAUD_CARD_TEST_DISTINCT_CARDS', 3)
    since = timezone.now() - timedelta(minutes=window_minutes)

    recent = PaymentAttempt.objects.filter(customer=customer, created_at__gte=since)
    recent_failures = recent.filter(success=False).count()
    distinct_cards  = recent.exclude(card_fingerprint='').values('card_fingerprint').distinct().count()

    if recent_failures >= fail_threshold or distinct_cards >= card_threshold:
        order = Order.objects.filter(customer=customer).order_by('-created_at').first()
        if order is None:
            # No order exists yet to attach the flag to (e.g. all attempts
            # failed before checkout completed) — nothing to hold a payout
            # on, but the attempts are still logged for later review.
            return True
        _create_flag(
            order=order,
            flag_type=FraudFlag.FlagType.CARD_TESTING,
            severity=FraudFlag.Severity.HIGH,
            reason=(
                f'{recent_failures} failed payment attempt(s) and {distinct_cards} distinct '
                f'card(s) used within {window_minutes} minutes.'
            ),
        )
        return True
    return False


# ── ORCHESTRATOR ───────────────────────────────────────────

def run_fraud_checks(order):
    """
    Runs every rule against this order. If anything fires, holds the
    vendor payout(s) tied to this order pending manual review. Call this
    once an order's payment is confirmed (wired automatically via
    fraud/signals.py — no payment-app changes needed for this part).
    """
    flagged = False
    if check_address_velocity(order):
        flagged = True
    if check_phone_velocity(order):
        flagged = True
    if check_card_testing(order.customer):
        flagged = True

    if flagged:
        _hold_vendor_payout(order)

    return flagged


# ── INTEGRATION POINT FOR THE PAYMENT APP ─────────────────

def record_payment_attempt(*, customer=None, order=None, card_fingerprint='',
                            amount=None, success=False, ip_address=None):
    """
    Call this from your payment app on EVERY charge attempt (success or
    failure) — e.g. inside the Flutterwave/Paystack webhook handler, right
    after you get the charge result back:

        from fraud.services import record_payment_attempt

        record_payment_attempt(
            customer=request.user if request.user.is_authenticated else None,
            order=order,                                  # if available yet
            card_fingerprint=charge_response['card']['token'],  # processor's own token — never raw PAN
            amount=amount,
            success=charge_response['status'] == 'successful',
            ip_address=request.META.get('REMOTE_ADDR'),
        )

    Without this call, check_card_testing() above has nothing to check
    against — the address/phone velocity checks work today without any
    payment-app changes, but card testing needs this one hook.
    """
    return PaymentAttempt.objects.create(
        customer=customer,
        order=order,
        card_fingerprint=card_fingerprint or '',
        amount=amount,
        success=success,
        ip_address=ip_address,
    )


# ── HELPERS ────────────────────────────────────────────────

def _create_flag(*, order, flag_type, severity, reason):
    # Avoid spamming duplicate flags of the same type on the same order.
    existing = FraudFlag.objects.filter(order=order, flag_type=flag_type, resolved=False).first()
    if existing:
        return existing
    return FraudFlag.objects.create(
        order=order, flag_type=flag_type, severity=severity, reason=reason
    )


def _hold_vendor_payout(order):
    # Imported here (not at module top) to avoid a hard import-time
    # dependency between the fraud and vendors apps.
    from vendors.models import VendorEarning
    VendorEarning.objects.filter(
        order=order, status=VendorEarning.Status.PENDING
    ).update(status=VendorEarning.Status.HELD)


def release_vendor_payout(order):
    """
    Inverse of _hold_vendor_payout — moves this order's VendorEarning rows
    back from HELD to PENDING. Call this from fraud/views.py (or the admin
    action) only once you've confirmed there are no other unresolved OR
    confirmed-fraud flags remaining on the order — releasing while a
    sibling flag is still open defeats the point of holding it.
    """
    from vendors.models import VendorEarning
    VendorEarning.objects.filter(
        order=order, status=VendorEarning.Status.HELD
    ).update(status=VendorEarning.Status.PENDING)