from django.db import models
from django.conf import settings
from django.utils.text import slugify
from django.db.models import Sum


# ── Vendor ─────────────────────────────────────────────────────────────────────

class Vendor(models.Model):

    class Status(models.TextChoices):
        PENDING   = 'pending',   'Pending Approval'
        ACTIVE    = 'active',    'Active'
        SUSPENDED = 'suspended', 'Suspended'

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vendor',
    )

    shop_name   = models.CharField(max_length=150)
    slug        = models.SlugField(unique=True, blank=True)
    description = models.TextField(blank=True)

    logo   = models.ImageField(upload_to='vendors/logos/',   blank=True, null=True)
    banner = models.ImageField(upload_to='vendors/banners/', blank=True, null=True)

    phone    = models.CharField(max_length=15)
    location = models.CharField(max_length=200, blank=True)

    # ── MoMo payout details ─────────────────────────────────────
    # These are used by payment/views._disburse_to_vendor() to send
    # the vendor their net amount (after commission) via Hubtel Transfers
    # the moment a customer's payment is confirmed.
    momo_number = models.CharField(
        max_length=15,
        blank=True,
        help_text='MoMo number to receive order payouts (e.g. 0241234567).',
    )
    momo_network = models.CharField(
        max_length=20,
        blank=True,
        choices=[
            ('mtn',        'MTN Mobile Money'),
            ('telecel',    'Telecel Cash'),       # formerly Vodafone
            ('vodafone',   'Vodafone Cash'),       # legacy label — maps to Telecel
            ('airteltigo', 'AirtelTigo Money'),
        ],
        help_text='Select the network of the MoMo number above.',
    )

    # ── Social links ─────────────────────────────────────────────
    facebook  = models.URLField(blank=True, null=True)
    instagram = models.URLField(blank=True, null=True)
    twitter   = models.URLField(blank=True, null=True)
    tiktok    = models.URLField(blank=True, null=True)
    youtube   = models.URLField(blank=True, null=True)
    whatsapp  = models.CharField(max_length=20, blank=True, null=True)

    status          = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=4.00)

    # paystack_subaccount_code REMOVED — Paystack replaced by Hubtel.
    # Vendor payouts now go directly to momo_number via Hubtel Transfers.

    joined_at   = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-joined_at']

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.shop_name)
            slug = base
            n    = 1
            while Vendor.objects.filter(slug=slug).exists():
                slug = f'{base}-{n}'
                n   += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def payout_phone(self):
        """
        Convenience property used by payment/views._disburse_to_vendor().
        Returns momo_number, falling back to phone if momo_number is empty.
        """
        return (self.momo_number or self.phone or '').strip()

    @property
    def hubtel_network_code(self):
        """
        Maps the vendor's momo_network to the code Hubtel Transfers expects.
        Hubtel network codes for Ghana: MTN, TELECEL, AIRTELTIGO
        """
        mapping = {
            'mtn':        'MTN',
            'telecel':    'TELECEL',
            'vodafone':   'TELECEL',    # Vodafone GH rebranded to Telecel
            'airteltigo': 'AIRTELTIGO',
        }
        return mapping.get(self.momo_network.lower(), 'MTN')

    @property
    def total_sales(self):
        from order.models import OrderItem
        return OrderItem.objects.filter(
            product__vendor=self,
            order__payment_status='paid',
        ).count()

    @property
    def total_revenue(self):
        from order.models import OrderItem
        return OrderItem.objects.filter(
            product__vendor=self,
            order__payment_status='paid',
        ).aggregate(total=Sum('subtotal'))['total'] or 0

    @property
    def whatsapp_link(self):
        if self.whatsapp:
            return f"https://wa.me/{self.whatsapp.replace('+', '').strip()}"
        return ''

    def __str__(self):
        return self.shop_name


# ── VendorEarning ──────────────────────────────────────────────────────────────

class VendorEarning(models.Model):

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        HELD    = 'held',    'Held (Fraud Review)'
        PAID    = 'paid',    'Paid Out'
        FAILED  = 'failed',  'Payout Failed'   # NEW: Hubtel transfer was rejected

    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        related_name='earnings',
    )
    order = models.ForeignKey(
        'order.Order',
        on_delete=models.CASCADE,
        related_name='vendor_earnings',
    )

    gross_amount = models.DecimalField(max_digits=10, decimal_places=2)
    commission   = models.DecimalField(max_digits=10, decimal_places=2)
    net_amount   = models.DecimalField(max_digits=10, decimal_places=2)

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # Hubtel disbursement tracking
    payout_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text='Hubtel Transfer clientReference for this payout.',
    )
    payout_error = models.TextField(
        blank=True,
        help_text='Error message if Hubtel payout failed — used for manual follow-up.',
    )

    paid_at    = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.vendor.shop_name} — GHS {self.net_amount} ({self.status})'


# ── AppCommission ──────────────────────────────────────────────────────────────

class AppCommission(models.Model):

    order  = models.ForeignKey(
        'order.Order',
        on_delete=models.CASCADE,
        related_name='commissions',
    )
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        related_name='commissions',
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    rate   = models.DecimalField(max_digits=5,  decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'GHS {self.amount} from {self.vendor.shop_name}'


# ── Referral ───────────────────────────────────────────────────────────────────

class Referral(models.Model):
    vendor      = models.ForeignKey('Vendor', on_delete=models.CASCADE)
    code        = models.CharField(max_length=20, unique=True)
    clicks      = models.PositiveIntegerField(default=0)
    conversions = models.PositiveIntegerField(default=0)
    created_at  = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.vendor.shop_name} — {self.code}'