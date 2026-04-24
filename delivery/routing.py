from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path("ws/delivery/<int:delivery_id>/", consumers.DeliveryConsumer.as_asgi()),
]