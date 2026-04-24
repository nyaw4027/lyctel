from django.db import models
from django.utils import timezone
from decimal import Decimal


# ─────────────────────────────
# DELIVERY ZONE
# ─────────────────────────────
class DeliveryZone(models.Model):
    name = models.CharField(max_length=100)
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2)
    estimated_days = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} — GHS {self.delivery_fee}"


# ─────────────────────────────
# DELIVERY MODEL
# ─────────────────────────────
class Delivery(models.Model):

    # ───── STATUS ─────
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ASSIGNED = "assigned", "Assigned"
        PICKED_UP = "picked_up", "Picked Up"
        EN_ROUTE = "en_route", "En Route"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"

    # ───── DELIVERY TYPE ─────
    class DeliveryType(models.TextChoices):
        STANDARD = "standard", "Standard Delivery"
        EXPRESS = "express", "Express Ride"

    # ───── RELATIONS ─────
    order = models.OneToOneField(
        "order.Order",
        on_delete=models.CASCADE,
        related_name="delivery",
        null=True,
        blank=True
    )

    rider = models.ForeignKey(
        "rider.RiderProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deliveries"
    )

    zone = models.ForeignKey(
        DeliveryZone,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # ───── TYPE ─────
    delivery_type = models.CharField(
        max_length=20,
        choices=DeliveryType.choices,
        default=DeliveryType.STANDARD
    )

    # ───── STATUS ─────
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )

    # ───── PRICING ─────
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    rider_commission = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    # ───── DISTANCE + ETA ─────
    distance_km = models.FloatField(null=True, blank=True)
    estimated_duration = models.PositiveIntegerField(null=True, blank=True)

    # ───── LOCATIONS ─────
    pickup_location = models.CharField(max_length=255, blank=True)
    dropoff_location = models.CharField(max_length=255, blank=True)

    pickup_lat = models.FloatField(null=True, blank=True)
    pickup_lng = models.FloatField(null=True, blank=True)

    dropoff_lat = models.FloatField(null=True, blank=True)
    dropoff_lng = models.FloatField(null=True, blank=True)

    current_lat = models.FloatField(null=True, blank=True)
    current_lng = models.FloatField(null=True, blank=True)

    # ───── SECURITY ─────
    delivery_code = models.CharField(max_length=6, blank=True, null=True)

    # ───── PROOF ─────
    proof_of_delivery = models.ImageField(
        upload_to="deliveries/proofs/",
        null=True,
        blank=True
    )

    delivery_note = models.TextField(blank=True)

    # ───── TIMESTAMPS ─────
    assigned_at = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    # ─────────────────────────────
    # COMMISSION CALCULATION
    # ─────────────────────────────
    def calculate_commission(self):
        if self.rider and self.delivery_fee:
            rate = Decimal(getattr(self.rider, "commission_rate", 0)) / Decimal("100")
            return (Decimal(self.delivery_fee) * rate).quantize(Decimal("0.01"))
        return Decimal("0.00")

    # ─────────────────────────────
    # SAVE LOGIC (SMART PRICING)
    # ─────────────────────────────
    def save(self, *args, **kwargs):

        # EXPRESS DELIVERY PRICING
        if self.delivery_type == self.DeliveryType.EXPRESS and self.distance_km:
            base_fee = 5
            per_km = 2
            self.delivery_fee = round(base_fee + (self.distance_km * per_km), 2)

        # STANDARD ZONE PRICING
        elif self.delivery_type == self.DeliveryType.STANDARD and self.zone:
            self.delivery_fee = self.zone.delivery_fee

        # RIDER COMMISSION
        self.rider_commission = self.calculate_commission()

        super().save(*args, **kwargs)

    # ─────────────────────────────
    # STATUS HANDLER
    # ─────────────────────────────
    def set_status(self, status):
        self.status = status

        if status == self.Status.ASSIGNED:
            self.assigned_at = timezone.now()

        elif status == self.Status.PICKED_UP:
            self.picked_up_at = timezone.now()

        elif status == self.Status.DELIVERED:
            self.delivered_at = timezone.now()

        self.save()

    # ─────────────────────────────
    # AUTO RIDER ASSIGNMENT (SAFE)
    # ─────────────────────────────
    def assign_rider(self):
        from rider.models import RiderProfile

        rider = RiderProfile.objects.filter(
            status=RiderProfile.Status.AVAILABLE
        ).order_by("?").first()

        if rider:
            self.rider = rider
            self.status = self.Status.ASSIGNED
            self.assigned_at = timezone.now()
            self.save()

    # ─────────────────────────────
    # TRACKING HELPER
    # ─────────────────────────────
    def add_tracking(self, lat, lng):
        from .models import DeliveryTracking

        DeliveryTracking.objects.create(
            delivery=self,
            latitude=lat,
            longitude=lng
        )

        self.current_lat = lat
        self.current_lng = lng
        self.save(update_fields=["current_lat", "current_lng"])

    # ─────────────────────────────
    # HELPERS
    # ─────────────────────────────
    def is_active(self):
        return self.status not in [self.Status.DELIVERED, self.Status.FAILED]

    def is_pending(self):
        return self.status == self.Status.PENDING

    def is_in_transit(self):
        return self.status in [self.Status.PICKED_UP, self.Status.EN_ROUTE]

    def __str__(self):
        if self.order:
            return f"Delivery {self.order.order_ref} — {self.status}"
        return f"Ride Delivery — {self.status}"


# ─────────────────────────────
# DELIVERY TRACKING
class DeliveryTracking(models.Model):
    delivery = models.ForeignKey(
        Delivery,
        on_delete=models.CASCADE,
        related_name="tracking"
    )

    latitude = models.FloatField()
    longitude = models.FloatField()

    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        constraints = [
            models.UniqueConstraint(
                fields=["delivery"],
                name="unique_delivery_per_order"
            )
        ]