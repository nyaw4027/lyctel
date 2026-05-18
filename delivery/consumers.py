import json
from channels.generic.websocket import AsyncWebsocketConsumer


class DeliveryConsumer(AsyncWebsocketConsumer):
    """Customer/vendor watches a specific delivery on the live map."""

    async def connect(self):
        self.delivery_id = self.scope["url_route"]["kwargs"]["delivery_id"]
        self.room_group_name = f"delivery_{self.delivery_id}"
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def send_location(self, event):
        await self.send(text_data=json.dumps({
            "type": "location",
            "lat": event["lat"],
            "lng": event["lng"],
            "status": event.get("status", ""),
        }))

    async def delivery_status(self, event):
        await self.send(text_data=json.dumps({
            "type": "status",
            "status": event["status"],
        }))


class RiderConsumer(AsyncWebsocketConsumer):
    """Per-rider channel — receives new ride request prompts in real time."""

    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated or user.role != "rider":
            await self.close()
            return
        self.group_name = f"rider_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def ride_request(self, event):
        """Push a new ride request to the rider's browser."""
        await self.send(text_data=json.dumps({
            "type": "ride_request",
            "delivery_id": event["delivery_id"],
            "acceptance_id": event["acceptance_id"],
            "pickup": event["pickup"],
            "dropoff": event["dropoff"],
            "fee": event["fee"],
            "commission": event["commission"],
        }))
