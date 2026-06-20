# chat/models.py
import uuid
from django.db import models
from django.conf import settings


class ChatRoom(models.Model):
    """One room per (buyer, vendor) pair."""
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    buyer      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='chat_rooms_as_buyer'
    )
    vendor     = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE,
        related_name='chat_rooms'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('buyer', 'vendor')
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.buyer} ↔ {self.vendor.shop_name}"

    def last_message(self):
        return self.messages.order_by('-created_at').first()

    def unread_count_for(self, user):
        return self.messages.filter(is_read=False).exclude(sender=user).count()


class SupportRoom(models.Model):
    """
    A live support conversation between a customer and Lynctel admin/staff.
    Created the moment a customer opens "Get Help" — no separate ticket form,
    the first message becomes the report.
    """

    class Category(models.TextChoices):
        ORDER    = 'order',    'Order Issue'
        PAYMENT  = 'payment',  'Payment Issue'
        DELIVERY = 'delivery', 'Delivery Issue'
        VENDOR   = 'vendor',   'Vendor/Shop Issue'
        ACCOUNT  = 'account',  'Account Issue'
        OTHER    = 'other',    'Other'

    class Status(models.TextChoices):
        OPEN     = 'open',     'Open'
        ANSWERED = 'answered', 'Answered'
        RESOLVED = 'resolved', 'Resolved'

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer    = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='support_rooms'
    )
    # Staff member currently handling this room (optional — claimed on first reply)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='assigned_support_rooms'
    )
    category    = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    status      = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    subject     = models.CharField(max_length=200, blank=True)

    # Optional context links — auto-attached when reporting from an order/vendor/chat
    related_order_ref = models.CharField(max_length=50, blank=True)
    related_vendor     = models.ForeignKey(
        'vendors.Vendor', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='support_reports'
    )

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"Support: {self.customer} — {self.get_category_display()} ({self.status})"

    def last_message(self):
        return self.messages.order_by('-created_at').first()

    def unread_count_for(self, user):
        return self.messages.filter(is_read=False).exclude(sender=user).count()


class Message(models.Model):
    """
    A message in either a vendor ChatRoom or a SupportRoom.
    Exactly one of `room` / `support_room` should be set.
    """
    room         = models.ForeignKey(
        ChatRoom, on_delete=models.CASCADE, related_name='messages',
        null=True, blank=True
    )
    support_room = models.ForeignKey(
        SupportRoom, on_delete=models.CASCADE, related_name='messages',
        null=True, blank=True
    )
    sender     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_messages'
    )
    content    = models.TextField(max_length=2000, blank=True)
    attachment = models.ImageField(upload_to='chat_attachments/%Y/%m/', null=True, blank=True)
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(room__isnull=False, support_room__isnull=True) |
                    models.Q(room__isnull=True, support_room__isnull=False)
                ),
                name='message_belongs_to_exactly_one_room_type',
            )
        ]

    def __str__(self):
        target = self.room or self.support_room
        return f"{self.sender} → {target} @ {self.created_at:%H:%M}"

    @property
    def has_attachment(self):
        return bool(self.attachment)