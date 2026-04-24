from django.db import models
from django.conf import settings
from django.db.models import Sum


# ─────────────────────────────
# RIDER PROFILE
# ─────────────────────────────
class RiderProfile(models.Model):

    class Status(models.TextChoices):
        AVAILABLE = 'available', 'Available'
        ON_DELIVERY = 'on_delivery', 'On Delivery'
        OFFLINE = 'offline', 'Offline'

    rider = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='rider_profile'
    )

    vehicle_type = models.CharField(max_length=50, blank=True)
    vehicle_plate = models.CharField(max_length=20, blank=True)

    id_card = models.ImageField(
        upload_to='riders/id_cards/',
        blank=True,
        null=True
    )

    zone = models.ForeignKey(
        'delivery.DeliveryZone',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.OFFLINE
    )

    is_verified = models.BooleanField(default=False)

    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=50.00,
        help_text="% of delivery fee rider gets"
    )

    # 📍 FOR AUTO ASSIGNMENT (IMPORTANT)
    current_lat = models.FloatField(null=True, blank=True)
    current_lng = models.FloatField(null=True, blank=True)

    joined_at = models.DateTimeField(auto_now_add=True)

    # ─────────────────────────────
    # TOTAL EARNINGS
    # ─────────────────────────────
    @property
    def total_earnings(self):
        return self.deliveries.filter(
            status='delivered'
        ).aggregate(
            total=Sum('rider_commission')
        )['total'] or 0

    def __str__(self):
        return f"{self.rider.get_full_name()} ({self.status})"


# ─────────────────────────────
# RIDER EARNINGS
# ─────────────────────────────
class RiderEarning(models.Model):

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PAID = 'paid', 'Paid'

    rider = models.ForeignKey(
        RiderProfile,
        on_delete=models.CASCADE,
        related_name='earnings'
    )

    delivery = models.OneToOneField(
        'delivery.Delivery',
        on_delete=models.CASCADE,
        related_name='earning'
    )

    amount = models.DecimalField(max_digits=8, decimal_places=2)

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING
    )

    paid_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.rider} — GHS {self.amount} — {self.status}"



from django.db import models
from django.conf import settings


class RiderLocation(models.Model):
    """Stores the rider's current GPS location — updated every 10s while on delivery."""
    rider      = models.OneToOneField(
                    settings.AUTH_USER_MODEL,
                    on_delete=models.CASCADE,
                    related_name='current_location'
                 )
    latitude   = models.DecimalField(max_digits=10, decimal_places=7, default=5.6037)
    longitude  = models.DecimalField(max_digits=10, decimal_places=7, default=-0.1870)
    updated_at = models.DateTimeField(auto_now=True)
    is_active  = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.rider} — {self.latitude}, {self.longitude}"


class DeliveryAcceptance(models.Model):
    """Tracks whether a rider accepted or rejected a delivery request."""
    class Status(models.TextChoices):
        PENDING  = 'pending',  'Pending'
        ACCEPTED = 'accepted', 'Accepted'
        REJECTED = 'rejected', 'Rejected'

    delivery   = models.OneToOneField(
                    'delivery.Delivery',
                    on_delete=models.CASCADE,
                    related_name='acceptance'
                 )
    rider      = models.ForeignKey(
                    'rider.RiderProfile',
                    on_delete=models.CASCADE,
                    related_name='acceptances'
                 )
    status     = models.CharField(
                    max_length=10,
                    choices=Status.choices,
                    default=Status.PENDING
                 )
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.rider} — {self.delivery} — {self.status}"