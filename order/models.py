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
        DISPATCHED = 'dispatched', 'Dispatched'
        DELIVERED  = 'delivered',  'Delivered'
        CANCELLED  = 'cancelled',  'Cancelled'
        REFUNDED   = 'refunded',   'Refunded'

    class PaymentStatus(models.TextChoices):
        UNPAID   = 'unpaid',   'Unpaid'
        PAID     = 'paid',     'Paid'
        FAILED   = 'failed',   'Failed'
        REFUNDED = 'refunded', 'Refunded'

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

    delivery_address = models.TextField()
    delivery_city    = models.CharField(max_length=100)
    delivery_phone   = models.CharField(max_length=20)

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

    # ─────────────────────────────
    # AUTO ORDER REF
    # ─────────────────────────────
    def save(self, *args, **kwargs):
        if not self.order_ref:
            self.order_ref = f"ORD-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    # ─────────────────────────────
    # AUTO TOTAL CALCULATION
    # ─────────────────────────────
    def calculate_totals(self):
        self.subtotal = sum(item.subtotal for item in self.items.all())
        self.total_amount = Decimal(self.subtotal) + Decimal(self.delivery_fee)
        self.save(update_fields=['subtotal', 'total_amount'])

    # ─────────────────────────────
    # HELPERS
    # ─────────────────────────────
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

    # ─────────────────────────────
    # SUBTOTAL
    # ─────────────────────────────
    @property
    def subtotal(self):
        return self.unit_price * self.quantity

    def save(self, *args, **kwargs):
        # auto-fill product name + price snapshot
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


