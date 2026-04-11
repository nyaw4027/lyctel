from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator


class Review(models.Model):
    product    = models.ForeignKey('products.Product', on_delete=models.CASCADE,
                                   related_name='reviews')
    customer   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   related_name='reviews')
    rating     = models.PositiveSmallIntegerField(
                    validators=[MinValueValidator(1), MaxValueValidator(5)])
    title      = models.CharField(max_length=100, blank=True)
    body       = models.TextField()
    is_visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        # One review per customer per product
        unique_together = ('product', 'customer')

    def __str__(self):
        return f"{self.customer.get_full_name()} — {self.product.name} ({self.rating}★)"

    @property
    def stars(self):
        return range(self.rating)

    @property
    def empty_stars(self):
        return range(5 - self.rating)