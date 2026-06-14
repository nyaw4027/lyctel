# chat/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone


class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.room_id   = self.scope['url_route']['kwargs']['room_id']
        self.room_group = f'chat_{self.room_id}'
        self.user       = self.scope['user']

        if not self.user.is_authenticated:
            await self.close()
            return

        # Verify user belongs to this room
        if not await self._user_in_room():
            await self.close()
            return

        await self.channel_layer.group_add(self.room_group, self.channel_name)
        await self.accept()

        # Mark existing messages as read
        await self._mark_read()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group, self.channel_name)

    async def receive(self, text_data):
        data    = json.loads(text_data)
        content = data.get('message', '').strip()
        if not content:
            return

        msg = await self._save_message(content)

        await self.channel_layer.group_send(
            self.room_group,
            {
                'type':       'chat_message',
                'message':    msg['content'],
                'sender_id':  msg['sender_id'],
                'sender_name':msg['sender_name'],
                'sender_pic': msg['sender_pic'],
                'timestamp':  msg['timestamp'],
                'msg_id':     msg['id'],
            }
        )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'message':    event['message'],
            'sender_id':  event['sender_id'],
            'sender_name':event['sender_name'],
            'sender_pic': event['sender_pic'],
            'timestamp':  event['timestamp'],
            'msg_id':     event['msg_id'],
        }))

    # ── DB helpers ────────────────────────────────────────
    @database_sync_to_async
    def _user_in_room(self):
        from .models import ChatRoom
        try:
            room = ChatRoom.objects.get(id=self.room_id)
            return (
                room.buyer_id == self.user.pk or
                room.vendor.owner_id == self.user.pk
            )
        except ChatRoom.DoesNotExist:
            return False

    @database_sync_to_async
    def _save_message(self, content):
        from .models import ChatRoom, Message
        room = ChatRoom.objects.get(id=self.room_id)
        msg  = Message.objects.create(room=room, sender=self.user, content=content)
        # Bump room updated_at so inbox sorts correctly
        room.updated_at = timezone.now()
        room.save(update_fields=['updated_at'])

        pic = ''
        if self.user.profile_pic:
            try:
                pic = self.user.profile_pic.url
            except Exception:
                pic = ''

        return {
            'id':          msg.pk,
            'content':     msg.content,
            'sender_id':   self.user.pk,
            'sender_name': self.user.get_full_name() or str(self.user.phone),
            'sender_pic':  pic,
            'timestamp':   msg.created_at.strftime('%H:%M'),
        }

    @database_sync_to_async
    def _mark_read(self):
        from .models import ChatRoom, Message
        try:
            room = ChatRoom.objects.get(id=self.room_id)
            Message.objects.filter(room=room, is_read=False).exclude(
                sender=self.user
            ).update(is_read=True)
        except ChatRoom.DoesNotExist:
            pass