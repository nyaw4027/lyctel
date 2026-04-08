import uuid
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

    order_ref        = models.CharField(max_length=20, unique=True, editable=False)
    customer         = models.ForeignKey(settings.AUTH_USER_MODEL,
                                         on_delete=models.SET_NULL,
                                         null=True, related_name='orders')
    delivery_address = models.TextField()
    delivery_city    = models.CharField(max_length=100)
    delivery_phone   = models.CharField(max_length=15)
    subtotal         = models.DecimalField(max_digits=10, decimal_places=2)
    delivery_fee     = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount     = models.DecimalField(max_digits=10, decimal_places=2)
    status           = models.CharField(max_length=15, choices=Status.choices,
                                        default=Status.PENDING)
    payment_status   = models.CharField(max_length=10, choices=PaymentStatus.choices,
                                        default=PaymentStatus.UNPAID)
    customer_note    = models.TextField(blank=True)
    admin_note       = models.TextField(blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)
    delivered_at     = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.order_ref:
            self.order_ref = f"ORD-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order_ref} — {self.status}"


class OrderItem(models.Model):
    order        = models.ForeignKey(Order, on_delete=models.CASCADE,
                                     related_name='items')
    product      = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    product_name = models.CharField(max_length=255)
    unit_price   = models.DecimalField(max_digits=10, decimal_places=2)
    quantity     = models.PositiveIntegerField()

    @property
    def subtotal(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.quantity}x {self.product_name}"


class OrderStatusHistory(models.Model):
    order      = models.ForeignKey(Order, on_delete=models.CASCADE,
                                   related_name='status_history')
    old_status = models.CharField(max_length=15, blank=True)
    new_status = models.CharField(max_length=15)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                   on_delete=models.SET_NULL, null=True)
    note       = models.TextField(blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']

    def __str__(self):
        return f"{self.order.order_ref}: {self.old_status} → {self.new_status}"