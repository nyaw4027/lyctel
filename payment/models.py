from django.db import models
from order.models import Order


class Payment(models.Model):
    class Method(models.TextChoices):
        MTN_MOMO      = 'mtn_momo',      'MTN Mobile Money'
        VODAFONE_CASH = 'vodafone_cash',  'Vodafone Cash'
        AIRTELTIGO    = 'airteltigo',     'AirtelTigo Money'
        CARD          = 'card',           'Bank Card'

    class Status(models.TextChoices):
        PENDING   = 'pending',   'Pending'
        SUCCESS   = 'success',   'Success'
        FAILED    = 'failed',    'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    order            = models.ForeignKey(Order, on_delete=models.CASCADE,
                                         related_name='payments')
    method           = models.CharField(max_length=20, choices=Method.choices)
    amount           = models.DecimalField(max_digits=10, decimal_places=2)
    currency         = models.CharField(max_length=5, default='GHS')
    status           = models.CharField(max_length=10, choices=Status.choices,
                                        default=Status.PENDING)
    transaction_id   = models.CharField(max_length=100, blank=True)
    gateway_ref      = models.CharField(max_length=100, blank=True)
    gateway_response = models.JSONField(default=dict, blank=True)
    momo_number      = models.CharField(max_length=15, blank=True)
    paid_at          = models.DateTimeField(null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.method} — GHS {self.amount} — {self.status}"