from django.db import models
from django.conf import settings

from order.models import Order


class FraudFlag(models.Model):
    """
    A single suspicious-pattern hit against an order. One order can have
    multiple flags (e.g. address velocity AND card testing at once) — each
    rule that fires creates its own row so the reason is always specific
    and auditable, rather than overwriting a single "is_flagged" boolean.
    """

    class FlagType(models.TextChoices):
        ADDRESS_VELOCITY = 'address_velocity', 'Multiple accounts, same address'
        PHONE_VELOCITY   = 'phone_velocity',   'Multiple accounts, same phone'
        CARD_TESTING     = 'card_testing',     'Card testing pattern'

    class Severity(models.TextChoices):
        LOW    = 'low',    'Low'
        MEDIUM = 'medium', 'Medium'
        HIGH   = 'high',   'High'

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='fraud_flags'
    )

    flag_type = models.CharField(max_length=20, choices=FlagType.choices)
    severity  = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MEDIUM)
    reason    = models.TextField(help_text="Human-readable explanation of what triggered this flag.")

    resolved        = models.BooleanField(default=False)
    # NEW: distinguishes "reviewed and it was nothing — release the payout"
    # from "reviewed and it WAS fraud — keep the payout held". Resolving a
    # flag isn't automatically the same as clearing it.
    is_confirmed_fraud = models.BooleanField(
        default=False,
        help_text="True if staff confirmed this was real fraud (payout stays held permanently). "
                   "False means cleared as a false positive (payout gets released, if no other open flags remain)."
    )
    resolved_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='resolved_fraud_flags'
    )
    resolved_at     = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_flag_type_display()} — {self.order.order_ref}"


class PaymentAttempt(models.Model):
    """
    Logged on EVERY charge attempt (success or failure) — this is the raw
    data the card-testing check runs against. A fraudster running stolen
    card numbers through checkout shows up here as many failed attempts
    (or many distinct card_fingerprints) in a short window.

    IMPORTANT: card_fingerprint must NEVER be a real card number. Use your
    payment processor's own card token (Flutterwave/Paystack both issue
    one), or a hash of (last4 + expiry) at most. Storing raw PANs is a
    PCI-DSS violation.
    """

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='payment_attempts'
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='payment_attempts',
        help_text="May be null — a failed attempt can happen before an Order exists yet."
    )

    card_fingerprint = models.CharField(max_length=128, blank=True)
    amount     = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    success    = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        status = 'OK' if self.success else 'FAILED'
        return f"PaymentAttempt[{status}] {self.created_at:%Y-%m-%d %H:%M}"