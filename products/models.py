from django.db import models
from django.utils.text import slugify
from django.core.validators import MinValueValidator


# ============================================================
# CATEGORY MODEL
# ============================================================
class Category(models.Model):

    class CategoryType(models.TextChoices):
        MAIN = "main", "Main Category"
        SUB = "sub", "Sub Category"

    name = models.CharField(max_length=100)

    slug = models.SlugField(
        unique=True,
        blank=True
    )

    # Parent Category (Nested Categories)
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

    icon = models.ImageField(
        upload_to="categories/",
        blank=True,
        null=True
    )

    banner = models.ImageField(
        upload_to="category_banners/",
        blank=True,
        null=True
    )

    description = models.TextField(blank=True)

    is_featured = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)

    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ["sort_order", "name"]
        unique_together = ("name", "parent")

    # --------------------------------------------------------
    # AUTO SAVE LOGIC
    # --------------------------------------------------------
    def save(self, *args, **kwargs):

        # Auto assign category type
        if self.parent:
            self.category_type = self.CategoryType.SUB
        else:
            self.category_type = self.CategoryType.MAIN

        # Auto slug generation
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1

            while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            self.slug = slug

        super().save(*args, **kwargs)

    # --------------------------------------------------------
    # HELPERS
    # --------------------------------------------------------
    @property
    def is_main_category(self):
        return self.parent is None

    @property
    def product_count(self):
        """
        FIXED:
        This now works safely with annotate().
        """
        return self.products.count()

    @property
    def subcategory_count(self):
        return self.subcategories.count()

    def get_full_path(self):
        """
        Example:
        Electronics > Phones > iPhones
        """
        path = [self.name]

        parent = self.parent

        while parent:
            path.append(parent.name)
            parent = parent.parent

        return " > ".join(reversed(path))

    def __str__(self):
        return self.get_full_path()


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

    slug = models.SlugField(
        unique=True,
        blank=True
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products"
    )

    description = models.TextField()

    short_description = models.CharField(
        max_length=255,
        blank=True
    )

    sku = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        null=True
    )

    barcode = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    brand = models.CharField(
        max_length=100,
        blank=True
    )

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
        null=True,
        help_text="Weight in KG"
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

        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["is_featured"]),
        ]

    # --------------------------------------------------------
    # AUTO SAVE
    # --------------------------------------------------------
    def save(self, *args, **kwargs):

        # Auto slug generation
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1

            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            self.slug = slug

        super().save(*args, **kwargs)

    # --------------------------------------------------------
    # PRODUCT HELPERS
    # --------------------------------------------------------
    @property
    def has_discount(self):
        return (
            self.discount_price is not None
            and self.discount_price < self.selling_price
        )

    @property
    def final_price(self):
        if self.has_discount:
            return self.discount_price

        return self.selling_price

    @property
    def discount_percent(self):

        if self.has_discount and self.selling_price > 0:

            return int(
                (
                    (self.selling_price - self.discount_price)
                    / self.selling_price
                ) * 100
            )

        return 0

    @property
    def is_in_stock(self):
        return self.stock_qty > 0

    @property
    def is_low_stock(self):
        return self.stock_qty <= self.low_stock_alert

    @property
    def is_hot_deal(self):
        return (
            self.has_discount
            and self.discount_percent >= 10
        )

    @property
    def primary_image(self):

        image = self.images.filter(is_primary=True).first()

        if image:
            return image.image.url

        fallback = self.images.first()

        if fallback:
            return fallback.image.url

        return None

    def __str__(self):

        vendor_name = (
            self.vendor.shop_name
            if self.vendor
            else "Store"
        )

        return f"[{vendor_name}] {self.name} — GHS {self.final_price}"


# ============================================================
# PRODUCT IMAGE MODEL
# ============================================================
class ProductImage(models.Model):

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="images"
    )

    image = models.ImageField(
        upload_to="products/"
    )

    is_primary = models.BooleanField(default=False)

    order = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]

    def save(self, *args, **kwargs):

        super().save(*args, **kwargs)

        # Ensure only ONE primary image
        if self.is_primary:

            ProductImage.objects.filter(
                product=self.product
            ).exclude(
                pk=self.pk
            ).update(is_primary=False)

    def __str__(self):
        return f"Image for {self.product.name}"


# ADD this model to your existing products/models.py
# Place it after your existing ProductImage model

class ProductVideo(models.Model):
    """
    Short video for a product (max 60 seconds recommended).
    Stored in Firebase Storage under media/product_videos/.
    """
    product     = models.ForeignKey(
        'Product', on_delete=models.CASCADE, related_name='videos'
    )
    video       = models.FileField(
        upload_to='product_videos/',
        help_text='MP4 recommended. Max 50MB. Keep under 60 seconds.'
    )
    thumbnail   = models.ImageField(
        upload_to='product_video_thumbs/',
        blank=True, null=True,
        help_text='Optional thumbnail image shown before video plays.'
    )
    title       = models.CharField(max_length=100, blank=True)
    order       = models.PositiveSmallIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'uploaded_at']

    def __str__(self):
        return f'Video for {self.product.name}'
