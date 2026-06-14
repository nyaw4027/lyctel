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


class Message(models.Model):
    room       = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages')
    sender     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_messages'
    )
    content    = models.TextField(max_length=2000)
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender} → {self.room} @ {self.created_at:%H:%M}"