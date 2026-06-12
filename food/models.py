from django.db import models

# Create your models here.
import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils.text import slugify
from django.utils import timezone


# ─────────────────────────────
# FOOD VENDOR (extends existing Vendor concept)
# ─────────────────────────────
class FoodVendor(models.Model):
    """
    A restaurant or food vendor on Lynctel Food.
    Linked to the existing Vendor model so the same
    user/shop can sell both products and food.
    """

    class CuisineType(models.TextChoices):
        GHANAIAN    = 'ghanaian',    'Ghanaian'
        CONTINENTAL = 'continental', 'Continental'
        CHINESE     = 'chinese',     'Chinese'
        FAST_FOOD   = 'fast_food',   'Fast Food'
        PIZZA       = 'pizza',       'Pizza'
        GRILLS      = 'grills',      'Grills & BBQ'
        SEAFOOD     = 'seafood',     'Seafood'
        VEGAN       = 'vegan',       'Vegan'
        DRINKS      = 'drinks',      'Drinks & Juices'
        BAKERY      = 'bakery',      'Bakery & Pastries'
        OTHER       = 'other',       'Other'

    class Status(models.TextChoices):
        OPEN      = 'open',      'Open'
        CLOSED    = 'closed',    'Closed'
        BUSY      = 'busy',      'Very Busy'
        SUSPENDED = 'suspended', 'Suspended'

    # Link to existing vendor (optional — can also be standalone)
    vendor = models.OneToOneField(
        'vendors.Vendor',
        on_delete=models.CASCADE,
        related_name='food_profile',
        null=True,
        blank=True,
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='food_vendors',
    )

    name        = models.CharField(max_length=150)
    slug        = models.SlugField(unique=True, blank=True)
    description = models.TextField(blank=True)
    cuisine     = models.CharField(
        max_length=20,
        choices=CuisineType.choices,
        default=CuisineType.GHANAIAN,
    )

    logo   = models.ImageField(upload_to='food/logos/',   blank=True, null=True)
    banner = models.ImageField(upload_to='food/banners/', blank=True, null=True)

    # Location
    address   = models.CharField(max_length=255)
    city      = models.CharField(max_length=100, default='Accra')
    latitude  = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    phone    = models.CharField(max_length=15)
    whatsapp = models.CharField(max_length=15, blank=True)

    # Operating hours (simple text for now)
    opening_time = models.TimeField(default='08:00')
    closing_time = models.TimeField(default='22:00')

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.OPEN,
    )

    # Delivery settings
    min_order      = models.DecimalField(max_digits=8, decimal_places=2, default=10)
    avg_prep_time  = models.PositiveIntegerField(default=20, help_text='Minutes')
    delivery_range = models.FloatField(default=10.0, help_text='Max delivery radius in km')

    # Stats
    total_orders = models.PositiveIntegerField(default=0)
    rating       = models.DecimalField(max_digits=3, decimal_places=1, default=0.0)

    is_featured = models.BooleanField(default=False)
    joined_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_featured', '-total_orders']

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)
            slug, n = base, 1
            while FoodVendor.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'; n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        if self.status != self.Status.OPEN:
            return False
        now = timezone.localtime().time()
        return self.opening_time <= now <= self.closing_time

    @property
    def logo_url(self):
        if self.logo:
            return self.logo.url
        return '/static/images/food-placeholder.png'

    @property
    def banner_url(self):
        if self.banner:
            return self.banner.url
        return '/static/images/food-banner-placeholder.png'

    def __str__(self):
        return self.name


# ─────────────────────────────
# FOOD CATEGORY
# ─────────────────────────────
class FoodCategory(models.Model):
    vendor = models.ForeignKey(
        FoodVendor,
        on_delete=models.CASCADE,
        related_name='food_categories',
    )
    name       = models.CharField(max_length=100)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return f'{self.vendor.name} — {self.name}'


# ─────────────────────────────
# FOOD ITEM
# ─────────────────────────────
class FoodItem(models.Model):
    vendor   = models.ForeignKey(
        FoodVendor,
        on_delete=models.CASCADE,
        related_name='food_items',
    )
    category = models.ForeignKey(
        FoodCategory,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='items',
    )

    name        = models.CharField(max_length=150)
    slug        = models.SlugField(blank=True)
    description = models.TextField(blank=True)
    image       = models.ImageField(upload_to='food/items/', blank=True, null=True)

    price         = models.DecimalField(max_digits=8, decimal_places=2)
    discount_price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    is_available = models.BooleanField(default=True)
    is_featured  = models.BooleanField(default=False)
    is_spicy     = models.BooleanField(default=False)
    is_vegan     = models.BooleanField(default=False)

    prep_time  = models.PositiveIntegerField(default=15, help_text='Minutes')
    sort_order = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'name']

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)
            slug, n = base, 1
            while FoodItem.objects.filter(
                vendor=self.vendor, slug=slug
            ).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'; n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def final_price(self):
        if self.discount_price and self.discount_price < self.price:
            return self.discount_price
        return self.price

    @property
    def image_url(self):
        if self.image:
            return self.image.url
        return '/static/images/food-placeholder.png'

    def __str__(self):
        return f'{self.name} — GHS {self.final_price}'


# ─────────────────────────────
# FOOD ORDER
# ─────────────────────────────
class FoodOrder(models.Model):

    class Status(models.TextChoices):
        PENDING    = 'pending',    'Pending'
        CONFIRMED  = 'confirmed',  'Confirmed'
        PREPARING  = 'preparing',  'Preparing'
        READY      = 'ready',      'Ready for Pickup'
        PICKED_UP  = 'picked_up',  'Picked Up'
        EN_ROUTE   = 'en_route',   'On the Way'
        DELIVERED  = 'delivered',  'Delivered'
        CANCELLED  = 'cancelled',  'Cancelled'

    class PaymentMethod(models.TextChoices):
        CASH_ON_DELIVERY = 'cash',  'Cash on Delivery'
        MOMO_ON_DELIVERY = 'momo_on_delivery', 'MoMo on Delivery'
        MOMO_PREPAID     = 'momo_prepaid',     'MoMo (Pay Now)'

    class PaymentStatus(models.TextChoices):
        UNPAID = 'unpaid', 'Unpaid'
        PAID   = 'paid',   'Paid'

    order_ref = models.CharField(max_length=20, unique=True, editable=False, db_index=True)

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='food_orders',
    )
    vendor = models.ForeignKey(
        FoodVendor,
        on_delete=models.SET_NULL,
        null=True,
        related_name='orders',
    )

    # Delivery details
    delivery_address = models.TextField()
    delivery_lat     = models.FloatField(null=True, blank=True)
    delivery_lng     = models.FloatField(null=True, blank=True)
    delivery_phone   = models.CharField(max_length=20)
    delivery_note    = models.TextField(blank=True)

    # Pricing
    subtotal     = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    distance_km  = models.FloatField(null=True, blank=True)

    # Payment
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH_ON_DELIVERY,
    )
    payment_status = models.CharField(
        max_length=10,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
    )

    # Status
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # Rider (linked to existing Delivery model)
    delivery = models.OneToOneField(
        'delivery.Delivery',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='food_order',
    )

    estimated_delivery_time = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Estimated minutes to deliver',
    )

    created_at   = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.order_ref:
            self.order_ref = f'FOOD-{uuid.uuid4().hex[:6].upper()}'
        self.total_amount = Decimal(self.subtotal) + Decimal(self.delivery_fee)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.order_ref} — {self.status}'


# ─────────────────────────────
# FOOD ORDER ITEM
# ─────────────────────────────
class FoodOrderItem(models.Model):
    order    = models.ForeignKey(FoodOrder, on_delete=models.CASCADE, related_name='items')
    food     = models.ForeignKey(FoodItem, on_delete=models.SET_NULL, null=True)
    name     = models.CharField(max_length=150)
    price    = models.DecimalField(max_digits=8, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    note     = models.CharField(max_length=200, blank=True)

    @property
    def subtotal(self):
        return self.price * self.quantity

    def save(self, *args, **kwargs):
        if self.food and not self.name:
            self.name  = self.food.name
            self.price = self.food.final_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.quantity}x {self.name}'


# ─────────────────────────────
# FOOD CART (session-based, stored in DB per user)
# ─────────────────────────────
class FoodCart(models.Model):
    customer   = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='food_cart',
    )
    vendor     = models.ForeignKey(
        FoodVendor,
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total(self):
        return sum(item.subtotal for item in self.cart_items.all())

    @property
    def item_count(self):
        return sum(item.quantity for item in self.cart_items.all())

    def __str__(self):
        return f'Cart — {self.customer}'


class FoodCartItem(models.Model):
    cart     = models.ForeignKey(FoodCart, on_delete=models.CASCADE, related_name='cart_items')
    food     = models.ForeignKey(FoodItem, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    note     = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = ('cart', 'food')

    @property
    def subtotal(self):
        return self.food.final_price * self.quantity

    def __str__(self):
        return f'{self.quantity}x {self.food.name}'