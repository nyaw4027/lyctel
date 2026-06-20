# chat/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


class BaseChatConsumer(AsyncWebsocketConsumer):
    """
    Shared logic for vendor chat and support chat.
    Subclasses set self.room_model and implement _user_can_access_room().
    """
    room_model = None  # set in subclass

    async def connect(self):
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'{self.group_prefix}_{self.room_id}'
        self.user = self.scope['user']

        if not self.user.is_authenticated:
            await self.close()
            return

        allowed = await self._user_can_access_room()
        if not allowed:
            await self.close()
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except (json.JSONDecodeError, TypeError):
            return

        message_type = data.get('type', 'message')

        if message_type == 'message':
            content    = (data.get('content') or '').strip()
            attachment_id = data.get('attachment_id')  # set when image was pre-uploaded via HTTP

            if not content and not attachment_id:
                return
            if content and len(content) > 2000:
                return

            message = await self._save_or_fetch_message(content, attachment_id)
            if not message:
                return

            payload = await self._build_message_payload(message)
            await self.channel_layer.group_send(
                self.room_group_name,
                {'type': 'chat_message', **payload}
            )

        elif message_type == 'typing':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type':      'typing_indicator',
                    'sender_id': self.user.pk,
                    'is_typing': bool(data.get('is_typing')),
                }
            )

        elif message_type == 'read':
            await self._mark_read()
            await self.channel_layer.group_send(
                self.room_group_name,
                {'type': 'read_receipt', 'reader_id': self.user.pk}
            )

    async def chat_message(self, event):
        event_copy = dict(event)
        event_copy.pop('type', None)
        event_copy['type'] = 'message'
        event_copy['is_self'] = event['sender_id'] == self.user.pk
        await self.send(text_data=json.dumps(event_copy))

    async def typing_indicator(self, event):
        if event['sender_id'] == self.user.pk:
            return
        await self.send(text_data=json.dumps({
            'type':      'typing',
            'sender_id': event['sender_id'],
            'is_typing': event['is_typing'],
        }))

    async def read_receipt(self, event):
        await self.send(text_data=json.dumps({
            'type':      'read',
            'reader_id': event['reader_id'],
        }))

    @database_sync_to_async
    def _save_or_fetch_message(self, content, attachment_id):
        from .models import Message
        if attachment_id:
            # Image already uploaded via HTTP endpoint; just attach text if any
            try:
                message = Message.objects.get(pk=attachment_id)
                if content:
                    message.content = content
                    message.save(update_fields=['content'])
                return message
            except Message.DoesNotExist:
                return None
        return self._create_text_message(content)

    def _create_text_message(self, content):
        raise NotImplementedError

    async def _build_message_payload(self, message):
        raise NotImplementedError

    async def _user_can_access_room(self):
        raise NotImplementedError

    async def _mark_read(self):
        raise NotImplementedError


class ChatConsumer(BaseChatConsumer):
    """Vendor ↔ Customer chat."""
    group_prefix = 'chat'

    @database_sync_to_async
    def _user_can_access_room(self):
        from .models import ChatRoom
        try:
            room = ChatRoom.objects.select_related('vendor').get(id=self.room_id)
        except ChatRoom.DoesNotExist:
            return False
        is_buyer  = room.buyer_id == self.user.pk
        is_vendor = hasattr(self.user, 'vendor') and room.vendor.owner_id == self.user.pk
        return is_buyer or is_vendor

    def _create_text_message(self, content):
        from .models import ChatRoom, Message
        from django.utils import timezone
        try:
            room = ChatRoom.objects.get(id=self.room_id)
        except ChatRoom.DoesNotExist:
            return None
        message = Message.objects.create(room=room, sender=self.user, content=content)
        ChatRoom.objects.filter(pk=room.pk).update(updated_at=timezone.now())
        return message

    @database_sync_to_async
    def _build_message_payload(self, message):
        from .models import ChatRoom
        room = ChatRoom.objects.select_related('vendor').get(id=self.room_id)
        is_vendor_sender = hasattr(self.user, 'vendor') and room.vendor.owner_id == message.sender_id
        return {
            'message_id':     message.id,
            'content':        message.content,
            'attachment_url': message.attachment.url if message.attachment else None,
            'sender_id':      message.sender_id,
            'sender_name':    message.sender.get_full_name() or message.sender.phone,
            'is_vendor':      is_vendor_sender,
            'created_at':     message.created_at.strftime('%H:%M'),
        }

    @database_sync_to_async
    def _mark_read(self):
        from .models import Message
        Message.objects.filter(room_id=self.room_id, is_read=False).exclude(
            sender=self.user
        ).update(is_read=True)


class SupportConsumer(BaseChatConsumer):
    """Customer ↔ Admin/Staff support chat."""
    group_prefix = 'support'

    @database_sync_to_async
    def _user_can_access_room(self):
        from .models import SupportRoom
        try:
            room = SupportRoom.objects.get(id=self.room_id)
        except SupportRoom.DoesNotExist:
            return False
        role = getattr(self.user, 'role', 'customer')
        is_owner = room.customer_id == self.user.pk
        is_staff = role in ('admin', 'staff')
        return is_owner or is_staff

    def _create_text_message(self, content):
        from .models import SupportRoom, Message
        from django.utils import timezone
        try:
            room = SupportRoom.objects.get(id=self.room_id)
        except SupportRoom.DoesNotExist:
            return None
        message = Message.objects.create(support_room=room, sender=self.user, content=content)

        update_fields = {'updated_at': timezone.now()}
        role = getattr(self.user, 'role', 'customer')
        if role in ('admin', 'staff'):
            if room.status == SupportRoom.Status.OPEN:
                update_fields['status'] = SupportRoom.Status.ANSWERED
            if not room.assigned_to_id:
                update_fields['assigned_to'] = self.user
        SupportRoom.objects.filter(pk=room.pk).update(**update_fields)
        return message

    @database_sync_to_async
    def _build_message_payload(self, message):
        role = getattr(message.sender, 'role', 'customer')
        return {
            'message_id':     message.id,
            'content':        message.content,
            'attachment_url': message.attachment.url if message.attachment else None,
            'sender_id':      message.sender_id,
            'sender_name':    message.sender.get_full_name() or message.sender.phone,
            'is_staff':       role in ('admin', 'staff'),
            'created_at':     message.created_at.strftime('%H:%M'),
        }

    @database_sync_to_async
    def _mark_read(self):
        from .models import Message
        Message.objects.filter(support_room_id=self.room_id, is_read=False).exclude(
            sender=self.user
        ).update(is_read=True)