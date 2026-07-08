# chat/consumers.py

import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from push_notifications import send_push_notification


class BaseChatConsumer(AsyncWebsocketConsumer):
    """
    Shared logic for Vendor Chat and Support Chat.
    """

    async def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.room_group_name = f"{self.group_prefix}_{self.room_id}"
        self.user = self.scope["user"]

        if not self.user.is_authenticated:
            await self.close()
            return

        if not await self._user_can_access_room():
            await self.close()
            return

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )

        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name,
            )

    async def receive(self, text_data):

        try:
            data = json.loads(text_data)
        except Exception:
            return

        msg_type = data.get("type", "message")

        if msg_type == "message":

            content = (data.get("content") or "").strip()
            attachment_id = data.get("attachment_id")

            if not content and not attachment_id:
                return

            if len(content) > 2000:
                return

            message = await self._save_or_fetch_message(
                content,
                attachment_id,
            )

            if not message:
                return

            payload = await self._build_message_payload(message)

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_message",
                    **payload,
                },
            )

        elif msg_type == "typing":

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "typing_indicator",
                    "sender_id": self.user.id,
                    "is_typing": bool(data.get("is_typing")),
                },
            )

        elif msg_type == "read":

            await self._mark_read()

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "read_receipt",
                    "reader_id": self.user.id,
                },
            )

    async def chat_message(self, event):

        payload = dict(event)
        payload.pop("type")

        payload["type"] = "message"
        payload["is_self"] = (
            payload["sender_id"] == self.user.id
        )

        await self.send(json.dumps(payload))

    async def typing_indicator(self, event):

        if event["sender_id"] == self.user.id:
            return

        await self.send(json.dumps({
            "type": "typing",
            "sender_id": event["sender_id"],
            "is_typing": event["is_typing"],
        }))

    async def read_receipt(self, event):

        await self.send(json.dumps({
            "type": "read",
            "reader_id": event["reader_id"],
        }))

    @database_sync_to_async
    def _save_or_fetch_message(self, content, attachment_id):

        from .models import Message

        if attachment_id:

            try:
                message = Message.objects.get(pk=attachment_id)

                if content:
                    message.content = content
                    message.save(update_fields=["content"])

                return message

            except Message.DoesNotExist:
                return None

        return self._create_text_message(content)

    def _create_text_message(self, content):
        raise NotImplementedError

    async def _build_message_payload(self, message):
        raise NotImplementedError

    async def _mark_read(self):
        raise NotImplementedError

    async def _user_can_access_room(self):
        raise NotImplementedError


# ==========================================================
# CUSTOMER ↔ VENDOR CHAT
# ==========================================================

class ChatConsumer(BaseChatConsumer):

    group_prefix = "chat"

    @database_sync_to_async
    def _user_can_access_room(self):

        from .models import ChatRoom

        try:
            room = ChatRoom.objects.select_related(
                "vendor"
            ).get(id=self.room_id)

        except ChatRoom.DoesNotExist:
            return False

        return (
            room.buyer_id == self.user.id
            or (
                hasattr(self.user, "vendor")
                and room.vendor.owner_id == self.user.id
            )
        )

    def _create_text_message(self, content):

        from django.utils import timezone
        from .models import ChatRoom, Message

        try:
            room = ChatRoom.objects.select_related(
                "vendor"
            ).get(id=self.room_id)

        except ChatRoom.DoesNotExist:
            return None

        message = Message.objects.create(
            room=room,
            sender=self.user,
            content=content,
        )

        ChatRoom.objects.filter(pk=room.pk).update(
            updated_at=timezone.now()
        )

        # Recipient
        if room.buyer_id == self.user.id:

            recipient = room.vendor.owner
            title = "New message from Customer"

        else:

            recipient = room.buyer
            title = "New message from Vendor"

        send_push_notification(
            recipient,
            title=title,
            body=content[:120] if content else "📷 Sent an image",
            url=f"/chat/{room.id}/",
        )

        return message

    @database_sync_to_async
    def _build_message_payload(self, message):

        from .models import ChatRoom

        room = ChatRoom.objects.select_related(
            "vendor"
        ).get(id=self.room_id)

        return {
            "message_id": message.id,
            "content": message.content,
            "attachment_url": (
                message.attachment.url
                if message.attachment else None
            ),
            "sender_id": message.sender_id,
            "sender_name": (
                message.sender.get_full_name()
                or message.sender.phone
            ),
            "is_vendor": (
                hasattr(message.sender, "vendor")
                and room.vendor.owner_id == message.sender_id
            ),
            "created_at": message.created_at.strftime("%H:%M"),
        }

    @database_sync_to_async
    def _mark_read(self):

        from .models import Message

        Message.objects.filter(
            room_id=self.room_id,
            is_read=False,
        ).exclude(
            sender=self.user,
        ).update(
            is_read=True,
        )


# ==========================================================
# SUPPORT CHAT
# ==========================================================

class SupportConsumer(BaseChatConsumer):

    group_prefix = "support"

    @database_sync_to_async
    def _user_can_access_room(self):

        from .models import SupportRoom

        try:
            room = SupportRoom.objects.get(id=self.room_id)

        except SupportRoom.DoesNotExist:
            return False

        role = getattr(self.user, "role", "customer")

        return (
            room.customer_id == self.user.id
            or role in ("admin", "staff")
        )

    def _create_text_message(self, content):

        from django.utils import timezone
        from .models import SupportRoom, Message

        try:
            room = SupportRoom.objects.get(id=self.room_id)

        except SupportRoom.DoesNotExist:
            return None

        message = Message.objects.create(
            support_room=room,
            sender=self.user,
            content=content,
        )

        update = {
            "updated_at": timezone.now(),
        }

        role = getattr(self.user, "role", "customer")

        if role in ("admin", "staff"):

            if room.status == SupportRoom.Status.OPEN:
                update["status"] = SupportRoom.Status.ANSWERED

            if not room.assigned_to_id:
                update["assigned_to"] = self.user

        SupportRoom.objects.filter(
            pk=room.pk
        ).update(**update)

        return message

    @database_sync_to_async
    def _build_message_payload(self, message):

        role = getattr(message.sender, "role", "customer")

        return {
            "message_id": message.id,
            "content": message.content,
            "attachment_url": (
                message.attachment.url
                if message.attachment else None
            ),
            "sender_id": message.sender_id,
            "sender_name": (
                message.sender.get_full_name()
                or message.sender.phone
            ),
            "is_staff": role in ("admin", "staff"),
            "created_at": message.created_at.strftime("%H:%M"),
        }

    @database_sync_to_async
    def _mark_read(self):

        from .models import Message

        Message.objects.filter(
            support_room_id=self.room_id,
            is_read=False,
        ).exclude(
            sender=self.user,
        ).update(
            is_read=True,
        )