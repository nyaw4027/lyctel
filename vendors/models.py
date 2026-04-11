from django.db import models
from django.conf import settings
from django.utils.text import slugify


class Vendor(models.Model):
    class Status(models.TextChoices):
        PENDING  = 'pending',  'Pending Approval'
        ACTIVE   = 'active',   'Active'
        SUSPENDED = 'suspended', 'Suspended'

    owner        = models.OneToOneField(settings.AUTH_USER_MODEL,
                                        on_delete=models.CASCADE,
                                        related_name='vendor')
    shop_name    = models.CharField(max_length=150)
    slug         = models.SlugField(unique=True)
    description  = models.TextField(blank=True)
    logo         = models.ImageField(upload_to='vendors/logos/', blank=True, null=True)
    banner       = models.ImageField(upload_to='vendors/banners/', blank=True, null=True)
    phone        = models.CharField(max_length=15)
    location     = models.CharField(max_length=200, blank=True)
    momo_number  = models.CharField(max_length=15, blank=True,
                                    help_text="MoMo number for payouts")
    momo_network = models.CharField(max_length=20, blank=True,
                                    choices=[('mtn','MTN'),('vodafone','Vodafone'),
                                             ('airteltigo','AirtelTigo')])
    status       = models.CharField(max_length=15, choices=Status.choices,
                                    default=Status.PENDING)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=10.00,
                                          help_text="% Lynctel takes from each sale")
    joined_at    = models.DateTimeField(auto_now_add=True)
    approved_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-joined_at']

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.shop_name)
            slug = base
            n = 1
            while Vendor.objects.filter(slug=slug).exists():
                slug = f"{base}-{n}"; n += 1
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
        from django.db.models import Sum
        from order.models import OrderItem
        result = OrderItem.objects.filter(
            product__vendor=self,
            order__payment_status='paid'
        ).aggregate(t=Sum('unit_price'))
        return result['t'] or 0

    def __str__(self):
        return f"{self.shop_name} ({self.status})"


class VendorEarning(models.Model):
    """Tracks earnings per order item for each vendor."""
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PAID    = 'paid',    'Paid Out'

    vendor       = models.ForeignKey(Vendor, on_delete=models.CASCADE,
                                     related_name='earnings')
    order        = models.ForeignKey('order.Order', on_delete=models.CASCADE,
                                     related_name='vendor_earnings')
    gross_amount = models.DecimalField(max_digits=10, decimal_places=2,
                                       help_text="Total sale before commission")
    commission   = models.DecimalField(max_digits=10, decimal_places=2,
                                       help_text="Amount taken by Lynctel (10%)")
    net_amount   = models.DecimalField(max_digits=10, decimal_places=2,
                                       help_text="Amount vendor receives")
    status       = models.CharField(max_length=10, choices=Status.choices,
                                    default=Status.PENDING)
    paid_at      = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.vendor.shop_name} — GHS {self.net_amount} ({self.status})"


class AppCommission(models.Model):
    """Tracks every commission earned by Lynctel (app owner)."""
    order        = models.ForeignKey('order.Order', on_delete=models.CASCADE,
                                     related_name='commissions')
    vendor       = models.ForeignKey(Vendor, on_delete=models.CASCADE,
                                     related_name='commissions')
    amount       = models.DecimalField(max_digits=10, decimal_places=2)
    rate         = models.DecimalField(max_digits=5, decimal_places=2)
    created_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Commission GHS {self.amount} from {self.vendor.shop_name}"