import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

import delivery.routing

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ecommerce.settings")

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            delivery.routing.websocket_urlpatterns
        )
    ),
})