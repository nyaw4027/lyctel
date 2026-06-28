"""
Fraud detection business logic.
Models (FraudFlag, PaymentAttempt) live in fraud/models.py — never here.
"""
from django.utils import timezone
from django.db.models import Count

from order.models import Order
from .models import FraudFlag, PaymentAttempt


# ── THRESHOLDS ────────────────────────────────────────────
ADDRESS_VELOCITY_WINDOW_DAYS = 30
ADDRESS_VELOCITY_LIMIT       = 3   # distinct accounts at same address
PHONE_VELOCITY_WINDOW_DAYS   = 30
PHONE_VELOCITY_LIMIT         = 3   # distinct accounts with same phone
CARD_TESTING_WINDOW_MINUTES  = 60
CARD_TESTING_FAIL_LIMIT      = 4   # failed attempts in window


def run_fraud_checks(order: Order):
    """
    Run all fraud rules against a freshly-paid order.
    Each rule that fires creates its own FraudFlag row.
    Never raises — fraud detection must never crash the payment flow.
    """
    try:
        _check_address_velocity(order)
    except Exception:
        pass
    try:
        _check_phone_velocity(order)
    except Exception:
        pass


def _check_address_velocity(order: Order):
    """Flag if multiple distinct accounts have ordered to the same address recently."""
    if not order.delivery_address:
        return

    since = timezone.now() - timezone.timedelta(days=ADDRESS_VELOCITY_WINDOW_DAYS)
    distinct_customers = (
        Order.objects
        .filter(
            delivery_address__iexact=order.delivery_address,
            created_at__gte=since,
            payment_status=Order.PaymentStatus.PAID,
        )
        .exclude(pk=order.pk)
        .values('customer')
        .distinct()
        .count()
    )

    if distinct_customers >= ADDRESS_VELOCITY_LIMIT:
        FraudFlag.objects.create(
            order=order,
            flag_type=FraudFlag.FlagType.ADDRESS_VELOCITY,
            severity=FraudFlag.Severity.MEDIUM,
            reason=(
                f"{distinct_customers + 1} distinct accounts have placed paid orders "
                f"to '{order.delivery_address}' in the last {ADDRESS_VELOCITY_WINDOW_DAYS} days."
            ),
        )


def _check_phone_velocity(order: Order):
    """Flag if the same delivery phone has been used by multiple accounts recently."""
    if not order.delivery_phone:
        return

    since = timezone.now() - timezone.timedelta(days=PHONE_VELOCITY_WINDOW_DAYS)
    distinct_customers = (
        Order.objects
        .filter(
            delivery_phone=order.delivery_phone,
            created_at__gte=since,
            payment_status=Order.PaymentStatus.PAID,
        )
        .exclude(pk=order.pk)
        .values('customer')
        .distinct()
        .count()
    )

    if distinct_customers >= PHONE_VELOCITY_LIMIT:
        FraudFlag.objects.create(
            order=order,
            flag_type=FraudFlag.FlagType.PHONE_VELOCITY,
            severity=FraudFlag.Severity.MEDIUM,
            reason=(
                f"{distinct_customers + 1} distinct accounts have used phone "
                f"'{order.delivery_phone}' in the last {PHONE_VELOCITY_WINDOW_DAYS} days."
            ),
        )


def record_payment_attempt(customer, order, card_fingerprint='', amount=None,
                            success=False, ip_address=None):
    """
    Call this from payment/views.py on every charge attempt (success or fail).
    This feeds the card-testing detection rule.

    Example usage in payment/views.py:
        from fraud.services import record_payment_attempt
        record_payment_attempt(
            customer=order.customer,
            order=order,
            card_fingerprint=data.get('card', {}).get('token', ''),
            amount=order.total_amount,
            success=(payment.status == Payment.Status.SUCCESS),
            ip_address=request.META.get('REMOTE_ADDR'),
        )
    """
    try:
        attempt = PaymentAttempt.objects.create(
            customer=customer,
            order=order,
            card_fingerprint=card_fingerprint,
            amount=amount,
            success=success,
            ip_address=ip_address,
        )
        if not success and customer:
            _check_card_testing(customer, order)
    except Exception:
        pass


def _check_card_testing(customer, order):
    """Flag if a customer has too many failed payment attempts in a short window."""
    since = timezone.now() - timezone.timedelta(minutes=CARD_TESTING_WINDOW_MINUTES)
    fail_count = PaymentAttempt.objects.filter(
        customer=customer,
        success=False,
        created_at__gte=since,
    ).count()

    if fail_count >= CARD_TESTING_FAIL_LIMIT:
        # Only create one flag per order — don't spam
        FraudFlag.objects.get_or_create(
            order=order,
            flag_type=FraudFlag.FlagType.CARD_TESTING,
            defaults={
                'severity': FraudFlag.Severity.HIGH,
                'reason': (
                    f"{fail_count} failed payment attempts in the last "
                    f"{CARD_TESTING_WINDOW_MINUTES} minutes from this account."
                ),
            }
        )