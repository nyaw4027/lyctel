import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings


class LiveStream(models.Model):

    class Status(models.TextChoices):
        SCHEDULED = 'scheduled', 'Scheduled'
        LIVE      = 'live',      'Live'
        ENDED     = 'ended',     'Ended'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    vendor = models.ForeignKey(
        'vendors.Vendor',
        on_delete=models.CASCADE,
        related_name='streams',
    )

    title       = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    thumbnail   = models.ImageField(
        upload_to='streams/thumbnails/', blank=True, null=True
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.SCHEDULED,
    )

    # ── Viewer tracking ───────────────────────────────────
    peak_viewers    = models.PositiveIntegerField(default=0)
    total_viewers   = models.PositiveIntegerField(default=0)
    current_viewers = models.PositiveIntegerField(default=0)

    # ── Revenue ───────────────────────────────────────────
    total_gifts_value = models.DecimalField(
        max_digits=10, decimal_places=2, default=0
    )
    total_sales_value = models.DecimalField(
        max_digits=10, decimal_places=2, default=0
    )

    # ── Timestamps ────────────────────────────────────────
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at   = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def is_live(self):
        return self.status == self.Status.LIVE

    @property
    def duration_minutes(self):
        if self.started_at and self.ended_at:
            return int((self.ended_at - self.started_at).total_seconds() / 60)
        return None

    # Lynctel takes 20% of all gifts
    PLATFORM_GIFT_CUT = Decimal('0.20')

    @property
    def platform_gift_earnings(self):
        return (self.total_gifts_value * self.PLATFORM_GIFT_CUT).quantize(
            Decimal('0.01')
        )

    def __str__(self):
        return f"{self.vendor.shop_name} — {self.title} [{self.status}]"


class StreamProduct(models.Model):
    """Products pinned to a stream — visible as buy cards in the viewer UI."""

    stream = models.ForeignKey(
        LiveStream,
        on_delete=models.CASCADE,
        related_name='pinned_products',
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='stream_pins',
    )

    is_highlighted = models.BooleanField(default=False)
    pinned_at      = models.DateTimeField(auto_now_add=True)
    order          = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering        = ['order', 'pinned_at']
        unique_together = ('stream', 'product')

    def __str__(self):
        return f"{self.product.name} @ {self.stream.title}"


class StreamGift(models.Model):
    """A viewer sends a virtual gift during a live stream."""

    class GiftType(models.TextChoices):
        ROSE    = 'rose',    '🌹 Rose'
        FIRE    = 'fire',    '🔥 Fire'
        DIAMOND = 'diamond', '💎 Diamond'
        CROWN   = 'crown',   '👑 Crown'
        ROCKET  = 'rocket',  '🚀 Rocket'

    # GHS value of each gift — Lynctel keeps 20%, vendor gets 80%
    GIFT_VALUES = {
        'rose':    Decimal('1.00'),
        'fire':    Decimal('2.00'),
        'diamond': Decimal('5.00'),
        'crown':   Decimal('10.00'),
        'rocket':  Decimal('20.00'),
    }

    GIFT_EMOJIS = {
        'rose':    '🌹',
        'fire':    '🔥',
        'diamond': '💎',
        'crown':   '👑',
        'rocket':  '🚀',
    }

    stream   = models.ForeignKey(
        LiveStream,
        on_delete=models.CASCADE,
        related_name='gifts',
    )
    sender   = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='sent_gifts',
    )

    gift_type = models.CharField(max_length=10, choices=GiftType.choices)
    quantity  = models.PositiveSmallIntegerField(default=1)

    # Snapshotted at send time
    unit_value      = models.DecimalField(max_digits=8, decimal_places=2)
    total_value     = models.DecimalField(max_digits=8, decimal_places=2)
    platform_cut    = models.DecimalField(max_digits=8, decimal_places=2)
    vendor_earnings = models.DecimalField(max_digits=8, decimal_places=2)

    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']

    def save(self, *args, **kwargs):
        self.unit_value      = self.GIFT_VALUES.get(self.gift_type, Decimal('1.00'))
        self.total_value     = self.unit_value * self.quantity
        self.platform_cut    = (self.total_value * Decimal('0.20')).quantize(Decimal('0.01'))
        self.vendor_earnings = self.total_value - self.platform_cut
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sender} sent {self.quantity}x {self.gift_type} = GHS {self.total_value}"


class StreamViewer(models.Model):
    """Tracks unique viewers per stream for analytics."""

    stream     = models.ForeignKey(
        LiveStream,
        on_delete=models.CASCADE,
        related_name='viewers',
    )
    user       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='watched_streams',
    )
    session_key = models.CharField(max_length=40, blank=True)  # for guests
    joined_at   = models.DateTimeField(auto_now_add=True)
    left_at     = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('stream', 'user')

    @property
    def watch_duration_seconds(self):
        if self.joined_at and self.left_at:
            return int((self.left_at - self.joined_at).total_seconds())
        return None

    def __str__(self):
        who = self.user.display_name if self.user else 'Guest'
        return f"{who} watched {self.stream.title}"


class StreamComment(models.Model):
    """Live chat message during a stream — stored for replay / moderation."""

    stream  = models.ForeignKey(
        LiveStream,
        on_delete=models.CASCADE,
        related_name='comments',
    )
    user    = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='stream_comments',
    )

    message    = models.CharField(max_length=300)
    is_pinned  = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    sent_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sent_at']

    def __str__(self):
        return f"{self.user}: {self.message[:50]}"