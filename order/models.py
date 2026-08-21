import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from products.models import Product


class Order(models.Model):

    class Status(models.TextChoices):
        PENDING    = 'pending',    'Pending'
        CONFIRMED  = 'confirmed',  'Confirmed'
        PROCESSING = 'processing', 'Processing'
        READY      = 'ready',      'Ready for Pickup'
        DISPATCHED = 'dispatched', 'Dispatched'
        DELIVERED  = 'delivered',  'Delivered'
        CANCELLED  = 'cancelled',  'Cancelled'
        REFUNDED   = 'refunded',   'Refunded'

    class PaymentStatus(models.TextChoices):
        UNPAID   = 'unpaid',   'Unpaid'
        PAID     = 'paid',     'Paid'
        FAILED   = 'failed',   'Failed'
        REFUNDED = 'refunded', 'Refunded'

    class DeliveryChoice(models.TextChoices):
        RIDER  = 'rider',  'Rider Delivery'
        PICKUP = 'pickup', 'Self Pickup'
        PARCEL = 'parcel', 'Bus / Parcel'

    order_ref = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        db_index=True
    )

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='orders'
    )

    # ── Delivery choice ───────────────────────────────────
    delivery_choice = models.CharField(
        max_length=10,
        choices=DeliveryChoice.choices,
        default=DeliveryChoice.RIDER,
    )

    # Used for rider mode
    delivery_address = models.TextField(blank=True)
    delivery_city    = models.CharField(max_length=100, blank=True)
    delivery_phone   = models.CharField(max_length=20, blank=True)
    
    delivery_lat = models.FloatField(null=True, blank=True)
    delivery_lng = models.FloatField(null=True, blank=True)

    # Used for parcel/bus mode
    parcel_bus_station     = models.CharField(max_length=255, blank=True)
    parcel_recipient_phone = models.CharField(max_length=20, blank=True)
    parcel_notes           = models.TextField(blank=True)
    parcel_waybill         = models.CharField(max_length=100, blank=True)
    parcel_dispatched_at   = models.DateTimeField(null=True, blank=True)

    # Used for pickup mode
    pickup_confirmed_at = models.DateTimeField(null=True, blank=True)

    # ── Financials ────────────────────────────────────────
    subtotal     = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    status         = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)

    customer_note = models.TextField(blank=True)
    admin_note    = models.TextField(blank=True)

    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    delivered_at = models.DateTimeField(null=True, blank=True)



    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.order_ref:
            self.order_ref = f"ORD-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    def calculate_totals(self):
        self.subtotal    = sum(item.subtotal for item in self.items.all())
        self.total_amount = Decimal(self.subtotal) + Decimal(self.delivery_fee)
        self.save(update_fields=['subtotal', 'total_amount'])

    # ── Delivery-mode helpers ─────────────────────────────

    @property
    def is_rider_delivery(self):
        return self.delivery_choice == self.DeliveryChoice.RIDER

    @property
    def is_pickup(self):
        return self.delivery_choice == self.DeliveryChoice.PICKUP

    @property
    def is_parcel(self):
        return self.delivery_choice == self.DeliveryChoice.PARCEL

    @property
    def delivery_choice_label(self):
        return {
            'rider':  '🛵 Rider Delivery',
            'pickup': '🏪 Self Pickup',
            'parcel': '🚌 Bus / Parcel',
        }.get(self.delivery_choice, self.delivery_choice)

    @property
    def is_paid(self):
        return self.payment_status == self.PaymentStatus.PAID

    @property
    def is_completed(self):
        return self.status == self.Status.DELIVERED

    def __str__(self):
        return f"{self.order_ref} — {self.status}"


class OrderItem(models.Model):

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items'
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True
    )

    product_name = models.CharField(max_length=255)
    unit_price   = models.DecimalField(max_digits=10, decimal_places=2)
    quantity     = models.PositiveIntegerField()

    class Meta:
        unique_together = ('order', 'product')

    @property
    def subtotal(self):
        return self.unit_price * self.quantity

    def save(self, *args, **kwargs):
        if self.product and not self.product_name:
            self.product_name = self.product.name
        if self.product and not self.unit_price:
            self.unit_price = self.product.selling_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity}x {self.product_name}"


class OrderStatusHistory(models.Model):

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='status_history'
    )

    old_status = models.CharField(max_length=15, blank=True)
    new_status = models.CharField(max_length=15)

    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )

    note = models.TextField(blank=True)

    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']

    def __str__(self):
        return f"{self.order.order_ref}: {self.old_status} → {self.new_status}"

     
class OrderDispute(models.Model):
 
    class Reason(models.TextChoices):
        NOT_DELIVERED = 'not_delivered', 'Item Not Delivered'
        WRONG_ITEM    = 'wrong_item',    'Wrong Item Received'
        DAMAGED       = 'damaged',       'Item Arrived Damaged'
        NOT_AS_DESC   = 'not_as_desc',   'Not As Described'
        MISSING_ITEM  = 'missing',       'Missing Item(s)'
        OVERCHARGED   = 'overcharged',   'Overcharged'
        OTHER         = 'other',         'Other'
 
    class Status(models.TextChoices):
        OPEN      = 'open',      'Open'
        REVIEWING = 'reviewing', 'Under Review'
        RESOLVED  = 'resolved',  'Resolved — Refund Approved'
        CLOSED    = 'closed',    'Closed — No Action'
 
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order       = models.OneToOneField(
        'Order', on_delete=models.CASCADE, related_name='dispute'
    )
    customer    = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='disputes'
    )
 
    reason           = models.CharField(max_length=20, choices=Reason.choices)
    description      = models.TextField(help_text='Describe the issue in detail')
    evidence         = models.ImageField(
        upload_to='disputes/%Y/%m/', null=True, blank=True,
        help_text='Optional photo evidence'
    )
    refund_requested = models.BooleanField(default=False)
 
    # Vendor response
    vendor_response  = models.TextField(blank=True)
    vendor_responded_at = models.DateTimeField(null=True, blank=True)
 
    # Staff fields
    staff_notes      = models.TextField(blank=True)
    assigned_to      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='assigned_disputes'
    )
    resolution       = models.TextField(blank=True)
 
    status      = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN
    )
 
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
 
    class Meta:
        ordering = ['-created_at']
 
    def __str__(self):
        return f"Dispute: {self.order.order_ref} — {self.get_reason_display()} ({self.status})"
 
    @property
    def is_open(self):
        return self.status in (self.Status.OPEN, self.Status.REVIEWING)
 
    @property
    def vendor(self):
        """Convenience: get vendor from first order item."""
        item = self.order.items.select_related('product__vendor').first()
        return item.product.vendor if item and item.product else None
 