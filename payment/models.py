import uuid
from django.db import models
from django.utils import timezone
from order.models import Order


class Payment(models.Model):

    class Method(models.TextChoices):
        MTN_MOMO      = 'mtn_momo',      'MTN Mobile Money'
        VODAFONE_CASH = 'vodafone_cash', 'Vodafone Cash'
        AIRTELTIGO    = 'airteltigo',    'AirtelTigo Money'
        CARD          = 'card',          'Bank Card'

    class Status(models.TextChoices):
        PENDING   = 'pending',   'Pending'
        SUCCESS   = 'success',   'Success'
        FAILED    = 'failed',    'Failed'
        CANCELLED = 'cancelled', 'Cancelled'
        REFUNDED  = 'refunded',  'Refunded'

    class Provider(models.TextChoices):
        FLUTTERWAVE = 'flutterwave', 'Flutterwave'
        PAYSTACK    = 'paystack',    'Paystack'

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='payments'
    )

    method = models.CharField(
        max_length=20,
        choices=Method.choices
    )

    # ── NEW: which gateway processed this payment ──────────
    provider = models.CharField(
        max_length=20,
        choices=Provider.choices,
        default=Provider.FLUTTERWAVE,
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    currency = models.CharField(
        max_length=5,
        default='GHS'
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING
    )

    # Gateway identifiers
    transaction_id = models.CharField(
        max_length=100,
        unique=True
    )

    gateway_ref = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    gateway_response = models.JSONField(
        default=dict,
        blank=True
    )

    momo_number = models.CharField(
        max_length=15,
        blank=True,
        null=True
    )

    paid_at = models.DateTimeField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['transaction_id']),
            models.Index(fields=['status']),
            models.Index(fields=['method']),
            models.Index(fields=['provider']),   # ← new index
        ]

    # ── Helpers ────────────────────────────────────────────
    def mark_success(self, gateway_ref=None, response=None):
        self.status          = self.Status.SUCCESS
        self.gateway_ref     = gateway_ref
        self.gateway_response = response or {}
        self.paid_at         = timezone.now()
        self.save()

    def mark_failed(self, response=None):
        self.status           = self.Status.FAILED
        self.gateway_response = response or {}
        self.save()

    @property
    def is_paid(self):
        return self.status == self.Status.SUCCESS

    @property
    def channel_display(self):
        """Human-readable channel shown on receipts/dashboard."""
        if self.provider == self.Provider.PAYSTACK:
            channel = (self.gateway_response or {}).get('channel', '')
            return f"Paystack · {channel.replace('_', ' ').title()}" if channel else 'Paystack'
        return self.get_method_display()

    def __str__(self):
        return f"{self.order.order_ref} | {self.provider} | {self.method} | GHS {self.amount} | {self.status}"


# ── PAYMENT LOG ────────────────────────────────────────────
class PaymentLog(models.Model):
    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name='logs'
    )

    event      = models.CharField(max_length=100)
    data       = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.payment.transaction_id} | {self.event}"