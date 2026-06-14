# chat/urls.py
from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    path('',                        views.inbox,      name='inbox'),
    path('<uuid:room_id>/',         views.room,       name='room'),
    path('start/<slug:vendor_slug>/',views.start_chat, name='start'),
    path('unread/',                 views.unread_count, name='unread_count'),
]