import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecommerce.settings')

django_asgi_app = get_asgi_application()

# Import all WebSocket URL patterns
from chat.routing     import websocket_urlpatterns as chat_ws
from delivery.routing import websocket_urlpatterns as delivery_ws
from livestream.routing import websocket_urlpatterns as livestream_ws

# Combine all WebSocket routes into one router
all_websocket_urlpatterns = (
    chat_ws +
    delivery_ws +
    livestream_ws
)

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AuthMiddlewareStack(
        URLRouter(all_websocket_urlpatterns)
    ),
})