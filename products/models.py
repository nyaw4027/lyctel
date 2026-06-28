from django.db import models
from django.utils.text import slugify
from django.core.validators import MinValueValidator, FileExtensionValidator
from django.core.exceptions import ValidationError


def validate_video_file_size(value):
    """
    FIXED: ProductVideo previously accepted any file of any size with no
    validation at all, even though the upload form/UI promised a 50MB cap
    and MP4/MOV/WebM only. This enforces the size side of that promise at
    the model level (in addition to the matching checks done in the view).
    """
    max_mb = 50
    if value.size > max_mb * 1024 * 1024:
        raise ValidationError(f"Video file too large. Max size is {max_mb}MB.")


# ============================================================
# CATEGORY MODEL
# ============================================================
class Category(models.Model):

    class CategoryType(models.TextChoices):
        MAIN = "main", "Main Category"
        SUB = "sub", "Sub Category"

    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)

    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="subcategories",
        null=True,
        blank=True
    )

    category_type = models.CharField(
        max_length=10,
        choices=CategoryType.choices,
        default=CategoryType.MAIN
    )

    icon = models.ImageField(upload_to="categories/", blank=True, null=True)
    banner = models.ImageField(upload_to="category_banners/", blank=True, null=True)

    description = models.TextField(blank=True)

    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ["sort_order", "name"]
        unique_together = ("name", "parent")

    def save(self, *args, **kwargs):

        if self.parent:
            self.category_type = self.CategoryType.SUB
        else:
            self.category_type = self.CategoryType.MAIN

        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1

            while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            self.slug = slug

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# ============================================================
# PRODUCT MODEL
# ============================================================
class Product(models.Model):

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        OUT_OF_STOCK = "out_of_stock", "Out of Stock"
        HIDDEN = "hidden", "Hidden"

    vendor = models.ForeignKey(
        "vendors.Vendor",
        on_delete=models.CASCADE,
        related_name="products",
        null=True,
        blank=True
    )

    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True)

    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products"
    )

    description = models.TextField()
    short_description = models.CharField(max_length=255, blank=True)

    sku = models.CharField(max_length=100, unique=True, blank=True, null=True)
    barcode = models.CharField(max_length=100, blank=True, null=True)

    brand = models.CharField(max_length=100, blank=True)

    cost_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )

    selling_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )

    discount_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True
    )

    stock_qty = models.PositiveIntegerField(default=0)
    low_stock_alert = models.PositiveIntegerField(default=5)

    weight = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        blank=True,
        null=True
    )

    views = models.PositiveIntegerField(default=0)
    sold_count = models.PositiveIntegerField(default=0)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE
    )

    is_featured = models.BooleanField(default=False)
    is_digital = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):

        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1

            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            self.slug = slug

        super().save(*args, **kwargs)

    @property
    def has_discount(self):
        return (
            self.discount_price is not None
            and self.discount_price < self.selling_price
        )

    @property
    def final_price(self):
        return self.discount_price if self.has_discount else self.selling_price

    @property
    def discount_percent(self):
        if self.has_discount and self.selling_price > 0:
            return int(
                ((self.selling_price - self.discount_price) /
                 self.selling_price) * 100
            )
        return 0

    @property
    def is_in_stock(self):
        return self.stock_qty > 0

    @property
    def is_low_stock(self):
        return self.stock_qty <= self.low_stock_alert

    @property
    def primary_image(self):
        img = self.images.filter(is_primary=True).first()
        if img:
            return img.image.url

        fallback = self.images.first()
        return fallback.image.url if fallback else None

    def __str__(self):
        vendor_name = self.vendor.shop_name if self.vendor else "Store"
        return f"{vendor_name} - {self.name}"


# ============================================================
# PRODUCT IMAGE MODEL (CLEAN — NO FIREBASE)
# ============================================================
class ProductImage(models.Model):

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="images"
    )

    image = models.ImageField(upload_to="products/")

    is_primary = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        if self.is_primary:
            ProductImage.objects.filter(
                product=self.product
            ).exclude(pk=self.pk).update(is_primary=False)

    def __str__(self):
        return f"Image - {self.product.name}"


# ============================================================
# PRODUCT VIDEO MODEL (CLEAN — NO FIREBASE)
# ============================================================
class ProductVideo(models.Model):

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='videos'
    )

    # FIXED: previously had no validators at all, despite the upload UI
    # advertising "MP4, MOV or WebM · Max 50MB". Now enforced at the model
    # level too (the view also checks this explicitly before .create()).
    video = models.FileField(
        upload_to='product_videos/',
        validators=[
            FileExtensionValidator(allowed_extensions=['mp4', 'mov', 'webm']),
            validate_video_file_size,
        ],
    )

    thumbnail = models.ImageField(
        upload_to='product_video_thumbs/',
        blank=True,
        null=True
    )

    title = models.CharField(max_length=100, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'uploaded_at']

    def __str__(self):
        return f"Video - {self.product.name}"