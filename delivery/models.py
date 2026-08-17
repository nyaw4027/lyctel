from django.conf import settings
from django.db import models
from django.utils import timezone
from decimal import Decimal


class DeliveryZone(models.Model):
    name           = models.CharField(max_length=100)
    delivery_fee   = models.DecimalField(max_digits=8, decimal_places=2)
    estimated_days = models.PositiveSmallIntegerField(default=1)
    is_active      = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} — GHS {self.delivery_fee}'


class Delivery(models.Model):

    class Status(models.TextChoices):
        PENDING   = 'pending',   'Pending'
        ASSIGNED  = 'assigned',  'Assigned'
        PICKED_UP = 'picked_up', 'Picked Up'
        EN_ROUTE  = 'en_route',  'En Route'
        DELIVERED = 'delivered', 'Delivered'
        FAILED    = 'failed',    'Failed'

    class DeliveryType(models.TextChoices):
        STANDARD = 'standard', 'Standard Delivery'
        EXPRESS  = 'express',  'Express Ride'

    order  = models.OneToOneField('order.Order', on_delete=models.CASCADE,
                                   related_name='delivery', null=True, blank=True)
    booker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                null=True, blank=True, related_name='booked_rides')
    rider  = models.ForeignKey('rider.RiderProfile', on_delete=models.SET_NULL,
                                null=True, blank=True, related_name='deliveries')
    zone   = models.ForeignKey(DeliveryZone, on_delete=models.SET_NULL,
                                null=True, blank=True)

    delivery_type = models.CharField(max_length=20, choices=DeliveryType.choices,
                                      default=DeliveryType.STANDARD)
    status        = models.CharField(max_length=20, choices=Status.choices,
                                      default=Status.PENDING)

    delivery_fee     = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    rider_commission = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    distance_km        = models.FloatField(null=True, blank=True)
    estimated_duration = models.PositiveIntegerField(null=True, blank=True)

    pickup_location  = models.CharField(max_length=255, blank=True)
    dropoff_location = models.CharField(max_length=255, blank=True)
    pickup_lat       = models.FloatField(null=True, blank=True)
    pickup_lng       = models.FloatField(null=True, blank=True)
    dropoff_lat      = models.FloatField(null=True, blank=True)
    dropoff_lng      = models.FloatField(null=True, blank=True)
    current_lat      = models.FloatField(null=True, blank=True)
    current_lng      = models.FloatField(null=True, blank=True)

    delivery_code      = models.CharField(max_length=6, blank=True, null=True)
    proof_of_delivery  = models.ImageField(upload_to='deliveries/proofs/',
                                            null=True, blank=True)
    delivery_note      = models.TextField(blank=True)

    assigned_at  = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    # ── Commission: 95% to rider, 5% to app ─────────────────────────────
    def calculate_commission(self):
        """
        FIXED: was using rider.commission_rate (default 50%).
        Now uses delivery/utils.calculate_rider_commission() → 95%.
        """
        if not self.delivery_fee:
            return Decimal('0.00')
        from delivery.utils import calculate_rider_commission
        return calculate_rider_commission(Decimal(str(self.delivery_fee)))

    # ── Smart pricing ─────────────────────────────────────────────────────
    def save(self, *args, **kwargs):
        if self.delivery_type == self.DeliveryType.EXPRESS and self.distance_km:
            self.delivery_fee = round(5 + (self.distance_km * 2.50), 2)
        elif self.delivery_type == self.DeliveryType.STANDARD and self.zone:
            self.delivery_fee = self.zone.delivery_fee
        self.rider_commission = self.calculate_commission()
        super().save(*args, **kwargs)

    # ── Status helper ─────────────────────────────────────────────────────
    def set_status(self, status):
        self.status = status
        if status == self.Status.ASSIGNED:   self.assigned_at  = timezone.now()
        elif status == self.Status.PICKED_UP: self.picked_up_at = timezone.now()
        elif status == self.Status.DELIVERED: self.delivered_at = timezone.now()
        self.save()

    # ── Auto-assign: FIXED — uses find_best_rider() not ORDER BY "?" ─────
    def assign_rider(self):
        """
        FIXED: was using .order_by('?').first() (random).
        Now delegates to delivery/services.find_best_rider() which scores
        riders by distance to pickup + active job workload.
        """
        from delivery.services import find_best_rider, assign_rider_to_delivery
        assign_rider_to_delivery(self, notify=True)

    # ── Tracking ──────────────────────────────────────────────────────────
    def add_tracking(self, lat, lng):
        DeliveryTracking.objects.create(delivery=self, latitude=lat, longitude=lng)
        self.current_lat = lat
        self.current_lng = lng
        self.save(update_fields=['current_lat', 'current_lng'])

    # ── State helpers ─────────────────────────────────────────────────────
    def is_active(self):
        return self.status not in [self.Status.DELIVERED, self.Status.FAILED]

    def is_pending(self):
        return self.status == self.Status.PENDING

    def is_in_transit(self):
        return self.status in [self.Status.PICKED_UP, self.Status.EN_ROUTE]

    def __str__(self):
        return (f'Delivery {self.order.order_ref} — {self.status}'
                if self.order else f'Ride Delivery — {self.status}')


class DeliveryTracking(models.Model):
    delivery  = models.ForeignKey(Delivery, on_delete=models.CASCADE,
                                   related_name='tracking')
    latitude  = models.FloatField()
    longitude = models.FloatField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']