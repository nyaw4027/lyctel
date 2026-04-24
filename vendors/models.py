from django.db import models
from django.conf import settings
from django.utils.text import slugify
from django.db.models import Sum


# ─────────────────────────────
# VENDOR MODEL
# ─────────────────────────────
class Vendor(models.Model):

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending Approval'
        ACTIVE = 'active', 'Active'
        SUSPENDED = 'suspended', 'Suspended'

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vendor'
    )

    shop_name = models.CharField(max_length=150)
    slug = models.SlugField(unique=True, blank=True)

    description = models.TextField(blank=True)

    logo = models.ImageField(upload_to='vendors/logos/', blank=True, null=True)
    banner = models.ImageField(upload_to='vendors/banners/', blank=True, null=True)

    phone = models.CharField(max_length=15)
    location = models.CharField(max_length=200, blank=True)

    momo_number = models.CharField(max_length=15, blank=True)
    momo_network = models.CharField(
        max_length=20,
        blank=True,
        choices=[
            ('mtn', 'MTN'),
            ('vodafone', 'Vodafone'),
            ('airteltigo', 'AirtelTigo')
        ]
    )

    facebook = models.URLField(blank=True, null=True)
    instagram = models.URLField(blank=True, null=True)
    twitter = models.URLField(blank=True, null=True)
    tiktok = models.URLField(blank=True, null=True)
    youtube = models.URLField(blank=True, null=True)

    whatsapp = models.CharField(max_length=20, blank=True, null=True)

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING
    )

    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=10.00)

    joined_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-joined_at']

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.shop_name)
            slug = base
            n = 1

            while Vendor.objects.filter(slug=slug).exists():
                slug = f"{base}-{n}"
                n += 1

            self.slug = slug

        super().save(*args, **kwargs)

    @property
    def total_sales(self):
        from order.models import OrderItem

        return OrderItem.objects.filter(
            product__vendor=self,
            order__payment_status='paid'
        ).count()

    @property
    def total_revenue(self):
        from order.models import OrderItem
        from django.db.models import Sum

        return OrderItem.objects.filter(
            product__vendor=self,
            order__payment_status='paid'
        ).aggregate(total=Sum('subtotal'))['total'] or 0

    # ✅ FIXED: NOW INSIDE CLASS
    @property
    def whatsapp_link(self):
        if self.whatsapp:
            number = self.whatsapp.replace("+", "").strip()
            return f"https://wa.me/{number}"
        return ""

# ─────────────────────────────
# VENDOR EARNINGS
# ─────────────────────────────
class VendorEarning(models.Model):

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PAID    = 'paid', 'Paid Out'

    vendor       = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        related_name='earnings'
    )

    order        = models.ForeignKey(
        'order.Order',
        on_delete=models.CASCADE,
        related_name='vendor_earnings'
    )

    gross_amount = models.DecimalField(max_digits=10, decimal_places=2)
    commission   = models.DecimalField(max_digits=10, decimal_places=2)
    net_amount   = models.DecimalField(max_digits=10, decimal_places=2)

    status       = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING
    )

    paid_at    = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.vendor.shop_name} — GHS {self.net_amount}"


# ─────────────────────────────
# PLATFORM COMMISSION (LYNCTEL)
# ─────────────────────────────
class AppCommission(models.Model):

    order      = models.ForeignKey(
        'order.Order',
        on_delete=models.CASCADE,
        related_name='commissions'
    )

    vendor     = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        related_name='commissions'
    )

    amount     = models.DecimalField(max_digits=10, decimal_places=2)
    rate       = models.DecimalField(max_digits=5, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"GHS {self.amount} from {self.vendor.shop_name}"



class Referral(models.Model):
    vendor = models.ForeignKey('Vendor', on_delete=models.CASCADE)
    code = models.CharField(max_length=20, unique=True)
    clicks = models.PositiveIntegerField(default=0)
    conversions = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.vendor.shop_name} - {self.code}"