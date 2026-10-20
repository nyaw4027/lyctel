"""
ecommerce/asgi.py

UPGRADE: Verified Redis channel layer is required for WebSockets to
work across multiple Railway workers. Without Redis, each worker has
its own in-memory channel layer — WebSocket messages from worker A
never reach clients connected to worker B.

Railway setup:
  1. Add the Redis plugin: Railway dashboard → + New → Redis
  2. Set REDIS_URL env var (Railway does this automatically)
  3. pip install channels-redis
"""
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecommerce.settings')

django_asgi_app = get_asgi_application()

from chat.routing      import websocket_urlpatterns as chat_ws
from delivery.routing  import websocket_urlpatterns as delivery_ws
from livestream.routing import websocket_urlpatterns as livestream_ws

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AuthMiddlewareStack(
        URLRouter(chat_ws + delivery_ws + livestream_ws)
    ),
})