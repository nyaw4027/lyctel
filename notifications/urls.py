from django.urls import path
from push_notifications import subscribe

urlpatterns = [
    path(
        "subscribe/",
        subscribe,
        name="push_subscribe",
    ),
]