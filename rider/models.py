from django.db import models
from django.conf import settings
from django.db.models import Sum
import uuid
from decimal import Decimal


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

    vehicle_type = models.CharField(
        max_length=50, blank=True, default='motorcycle',
        choices=[
            ('motorcycle', 'Motorcycle'),
            ('bicycle',    'Bicycle'),
            ('car',        'Car'),
            ('van',        'Van'),
            ('foot',       'On Foot'),
        ],
    )
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

    # MoMo details (settlement tracking only — no auto-transfer)
    momo_number  = models.CharField(
        max_length=15, blank=True, default='',
        help_text="Rider MoMo number for settlement records"
    )
    momo_network = models.CharField(
        max_length=15, blank=True, default='MTN',
        choices=[
            ('MTN',        'MTN Mobile Money'),
            ('VODAFONE',   'Vodafone Cash'),
            ('AIRTELTIGO', 'AirtelTigo Money'),
        ],
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    # ─────────────────────────────
    # TOTAL EARNINGS
    # ─────────────────────────────
    @property
    def total_deliveries(self):
        try:
            return self.deliveries.filter(status='delivered').count()
        except Exception:
            return 0

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


class RiderLedgerEntry(models.Model):
    """
    Created automatically when a delivery is completed and the customer
    paid the rider directly (cash or MoMo).
 
    Records:
      - gross_amount  : full delivery fee the customer paid
      - rider_net     : what the rider keeps (gross × commission_rate%)
      - app_commission: what the app is owed  (gross × app_rate%)
      - is_settled    : True once the rider has paid the app their cut
    """
 
    class PaymentMethod(models.TextChoices):
        CASH = 'cash', 'Cash'
        MOMO = 'momo', 'Mobile Money'
 
    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rider    = models.ForeignKey(
        'rider.RiderProfile',
        on_delete=models.CASCADE,
        related_name='ledger_entries',
    )
    delivery = models.OneToOneField(
        'delivery.Delivery',
        on_delete=models.CASCADE,
        related_name='ledger_entry',
    )
 
    gross_amount   = models.DecimalField(max_digits=10, decimal_places=2)
    rider_net      = models.DecimalField(max_digits=10, decimal_places=2)
    app_commission = models.DecimalField(max_digits=10, decimal_places=2)
    commission_pct = models.DecimalField(max_digits=5,  decimal_places=2,
                                          help_text="App % at time of delivery")
 
    payment_method = models.CharField(
        max_length=10,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )
 
    is_settled  = models.BooleanField(default=False)
    settled_at  = models.DateTimeField(null=True, blank=True)
    settled_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL,     # staffmember who confirmed payment
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='settled_ledger_entries',
    )
    settlement_note = models.TextField(blank=True)
 
    created_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        ordering = ['-created_at']
 
    def __str__(self):
        status = '✓' if self.is_settled else '⏳'
        return (f"{status} {self.rider} — GHS {self.app_commission} owed "
                f"({'settled' if self.is_settled else 'pending'})")
 
 
class RiderBalanceSummary(models.Model):
    """
    Running balance of how much each rider owes the app.
    Updated atomically on every completed delivery.
    Avoids re-aggregating ledger_entries on every page load.
    """
    rider           = models.OneToOneField(
        'rider.RiderProfile',
        on_delete=models.CASCADE,
        related_name='balance',
    )
    total_earned    = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_app_cut   = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_settled   = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    outstanding     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    updated_at      = models.DateTimeField(auto_now=True)
 
    def recalculate(self):
        from django.db.models import Sum, Q
        entries = self.rider.ledger_entries
        agg = entries.aggregate(
            gross  = Sum('gross_amount'),
            net    = Sum('rider_net'),
            app    = Sum('app_commission'),
            settled= Sum('app_commission', filter=Q(is_settled=True)),
        )
        self.total_earned  = agg['gross']  or Decimal('0')
        self.total_app_cut = agg['app']    or Decimal('0')
        self.total_settled = agg['settled']or Decimal('0')
        self.outstanding   = self.total_app_cut - self.total_settled
        self.save()
 
    class Meta:
        verbose_name_plural = 'Rider balance summaries'
 
    def __str__(self):
        return f"{self.rider} — owes GHS {self.outstanding}"