from django.db import models
from order.models import Order


class DeliveryZone(models.Model):
    name           = models.CharField(max_length=100)
    delivery_fee   = models.DecimalField(max_digits=8, decimal_places=2)
    estimated_days = models.PositiveSmallIntegerField(default=1)
    is_active      = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} — GHS {self.delivery_fee}"


class Delivery(models.Model):
    class Status(models.TextChoices):
        ASSIGNED  = 'assigned',  'Assigned'
        PICKED_UP = 'picked_up', 'Picked Up'
        EN_ROUTE  = 'en_route',  'En Route'
        DELIVERED = 'delivered', 'Delivered'
        FAILED    = 'failed',    'Failed'

    order             = models.OneToOneField(Order, on_delete=models.CASCADE,
                                             related_name='delivery')
    # String ref to avoid circular import with rider app
    rider             = models.ForeignKey('rider.RiderProfile',
                                          on_delete=models.SET_NULL,
                                          null=True, related_name='deliveries')
    zone              = models.ForeignKey(DeliveryZone, on_delete=models.SET_NULL,
                                          null=True)
    status            = models.CharField(max_length=15, choices=Status.choices,
                                         default=Status.ASSIGNED)
    delivery_fee      = models.DecimalField(max_digits=8, decimal_places=2)
    rider_commission  = models.DecimalField(max_digits=8, decimal_places=2)
    proof_of_delivery = models.ImageField(upload_to='deliveries/proofs/',
                                          blank=True, null=True)
    delivery_note     = models.TextField(blank=True)
    assigned_at       = models.DateTimeField(auto_now_add=True)
    picked_up_at      = models.DateTimeField(null=True, blank=True)
    delivered_at      = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.pk and self.rider:
            rate = self.rider.commission_rate / 100
            self.rider_commission = self.delivery_fee * rate
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Delivery for {self.order.order_ref} — {self.status}"