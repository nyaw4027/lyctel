import json
from channels.generic.websocket import AsyncWebsocketConsumer

class DeliveryConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.delivery_id = self.scope["url_route"]["kwargs"]["delivery_id"]
        self.room_group_name = f"delivery_{self.delivery_id}"

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def send_location(self, event):
        await self.send(text_data=json.dumps({
            "lat": event["lat"],
            "lng": event["lng"],
        }))
        