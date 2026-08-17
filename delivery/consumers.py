"""
delivery/consumers.py

FIXES:
  - DeliveryConsumer: auth check on connect — unauthenticated users rejected
  - DeliveryConsumer: only the order's customer, the assigned rider, or
    admin/staff may subscribe to a delivery's live location stream
  - RiderConsumer: unchanged (already had auth check)
"""
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


class DeliveryConsumer(AsyncWebsocketConsumer):
    """Customer/vendor/rider watches a specific delivery on the live map."""

    async def connect(self):
        user = self.scope['user']
        if not user.is_authenticated:
            await self.close(code=4401)
            return

        self.delivery_id    = self.scope['url_route']['kwargs']['delivery_id']
        self.room_group_name = f'delivery_{self.delivery_id}'

        # Authorise: customer, assigned rider, or staff/admin
        authorised = await self._is_authorised(user)
        if not authorised:
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def send_location(self, event):
        await self.send(text_data=json.dumps({
            'type':   'location',
            'lat':    event['lat'],
            'lng':    event['lng'],
            'status': event.get('status', ''),
        }))

    async def delivery_status(self, event):
        await self.send(text_data=json.dumps({
            'type':   'status',
            'status': event['status'],
        }))

    @database_sync_to_async
    def _is_authorised(self, user):
        if getattr(user, 'role', '') in ('admin', 'staff'):
            return True
        try:
            from delivery.models import Delivery
            d = Delivery.objects.select_related(
                'order__customer', 'rider__rider', 'booker'
            ).get(pk=self.delivery_id)
            if d.order and d.order.customer == user:
                return True
            if d.booker == user:
                return True
            if d.rider and d.rider.rider == user:
                return True
        except Exception:
            pass
        return False


class RiderConsumer(AsyncWebsocketConsumer):
    """Per-rider channel — receives new ride request prompts in real time."""

    async def connect(self):
        user = self.scope['user']
        if not user.is_authenticated or getattr(user, 'role', '') != 'rider':
            await self.close(code=4403)
            return
        self.group_name = f'rider_{user.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def ride_request(self, event):
        await self.send(text_data=json.dumps({
            'type':          'ride_request',
            'delivery_id':   event['delivery_id'],
            'acceptance_id': event['acceptance_id'],
            'pickup':        event['pickup'],
            'dropoff':       event['dropoff'],
            'fee':           event['fee'],
            'commission':    event['commission'],
        }))