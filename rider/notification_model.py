from django.db import models
from django.conf import settings


class RiderNotification(models.Model):
    class Type(models.TextChoices):
        NEW_DELIVERY = 'new_delivery', 'New Delivery'
        PAYMENT      = 'payment',      'Payment'
        GENERAL      = 'general',      'General'

    rider      = models.ForeignKey(
                    settings.AUTH_USER_MODEL,
                    on_delete=models.CASCADE,
                    related_name='rider_notifications'
                 )
    title      = models.CharField(max_length=200)
    message    = models.TextField()
    notif_type = models.CharField(max_length=20, choices=Type.choices, default=Type.GENERAL)
    link       = models.CharField(max_length=200, blank=True)
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.rider} — {self.title}"