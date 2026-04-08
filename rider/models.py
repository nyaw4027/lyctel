from django.db import models
from django.conf import settings
from delivery.models import DeliveryZone, Delivery


class RiderProfile(models.Model):
    class Status(models.TextChoices):
        AVAILABLE   = 'available',   'Available'
        ON_DELIVERY = 'on_delivery', 'On Delivery'
        OFFLINE     = 'offline',     'Offline'

    rider           = models.OneToOneField(settings.AUTH_USER_MODEL,
                                           on_delete=models.CASCADE,
                                           related_name='rider_profile')
    vehicle_type    = models.CharField(max_length=50, blank=True)
    vehicle_plate   = models.CharField(max_length=20, blank=True)
    id_card         = models.ImageField(upload_to='riders/id_cards/',
                                        blank=True, null=True)
    zone            = models.ForeignKey(DeliveryZone, on_delete=models.SET_NULL,
                                        null=True, blank=True)
    status          = models.CharField(max_length=15, choices=Status.choices,
                                       default=Status.OFFLINE)
    is_verified     = models.BooleanField(default=False)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2,
                                          default=50.00,
                                          help_text="% of delivery fee rider gets")
    joined_at       = models.DateTimeField(auto_now_add=True)

    @property
    def total_earnings(self):
        return self.deliveries.filter(
            status=Delivery.Status.DELIVERED
        ).aggregate(
            total=models.Sum('rider_commission')
        )['total'] or 0

    def __str__(self):
        return f"Rider: {self.rider.get_full_name()} ({self.status})"


class RiderEarning(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PAID    = 'paid',    'Paid'

    rider      = models.ForeignKey(RiderProfile, on_delete=models.CASCADE,
                                   related_name='earnings')
    delivery   = models.OneToOneField(Delivery, on_delete=models.CASCADE,
                                      related_name='earning')
    amount     = models.DecimalField(max_digits=8, decimal_places=2)
    status     = models.CharField(max_length=10, choices=Status.choices,
                                  default=Status.PENDING)
    paid_at    = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.rider} — GHS {self.amount} — {self.status}"