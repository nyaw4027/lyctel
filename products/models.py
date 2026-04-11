from django.db import models


class Category(models.Model):
    name        = models.CharField(max_length=100, unique=True)
    slug        = models.SlugField(unique=True)
    icon        = models.ImageField(upload_to='categories/', blank=True, null=True)
    description = models.TextField(blank=True)
    is_active   = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    class Status(models.TextChoices):
        ACTIVE        = 'active',        'Active'
        OUT_OF_STOCK  = 'out_of_stock',  'Out of Stock'
        HIDDEN        = 'hidden',        'Hidden'

    vendor          = models.ForeignKey(
                        'vendors.Vendor',
                        on_delete=models.CASCADE,
                        related_name='products',
                        null=True, blank=True,
                        help_text="Leave blank for your own products"
                      )
    name            = models.CharField(max_length=255)
    slug            = models.SlugField(unique=True)
    category        = models.ForeignKey(Category, on_delete=models.SET_NULL,
                                        null=True, related_name='products')
    description     = models.TextField()
    cost_price      = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price   = models.DecimalField(max_digits=10, decimal_places=2)
    stock_qty       = models.PositiveIntegerField(default=0)
    low_stock_alert = models.PositiveIntegerField(default=5)
    status          = models.CharField(max_length=15, choices=Status.choices,
                                       default=Status.ACTIVE)
    is_featured     = models.BooleanField(default=False)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def profit_margin(self):
        return self.selling_price - self.cost_price

    @property
    def is_in_stock(self):
        return self.stock_qty > 0

    @property
    def is_vendor_product(self):
        return self.vendor is not None

    def __str__(self):
        prefix = f"[{self.vendor.shop_name}] " if self.vendor else ""
        return f"{prefix}{self.name} — GHS {self.selling_price}"


class ProductImage(models.Model):
    product    = models.ForeignKey(Product, on_delete=models.CASCADE,
                                   related_name='images')
    image      = models.ImageField(upload_to='products/')
    is_primary = models.BooleanField(default=False)
    order      = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"Image for {self.product.name}"