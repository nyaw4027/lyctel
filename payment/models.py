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

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='payments'
    )

    method = models.CharField(
        max_length=20,
        choices=Method.choices
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

    # Flutterwave / gateway identifiers
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

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['transaction_id']),
            models.Index(fields=['status']),
            models.Index(fields=['method']),
        ]

    def mark_success(self, gateway_ref=None, response=None):
        """Mark payment as successful"""
        self.status = self.Status.SUCCESS
        self.gateway_ref = gateway_ref
        self.gateway_response = response or {}
        self.paid_at = timezone.now()
        self.save()

    def mark_failed(self, response=None):
        """Mark payment as failed"""
        self.status = self.Status.FAILED
        self.gateway_response = response or {}
        self.save()

    def __str__(self):
        return f"{self.order.order_ref} | {self.method} | GHS {self.amount} | {self.status}"

# 🔥 OPTIONAL BUT POWERFUL (PAYMENT LOGGING)

class PaymentLog(models.Model):
    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name='logs'
    )

    event = models.CharField(max_length=100)
    data = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.payment.transaction_id} | {self.event}"