# ── livestream/urls.py ────────────────────────────────────
from django.urls import path
from . import views

app_name = 'livestream'

urlpatterns = [
    path('',                                  views.stream_list,  name='list'),
    path('go-live/',                          views.go_live,      name='go_live'),
    path('<uuid:stream_id>/broadcast/',       views.broadcast,    name='broadcast'),
    path('<uuid:stream_id>/watch/',           views.watch,        name='watch'),
    path('<uuid:stream_id>/end/',             views.end_stream,   name='end_stream'),
    path('<uuid:stream_id>/pin-product/',     views.pin_product,  name='pin_product'),
    path('<uuid:stream_id>/send-gift/',       views.send_gift,    name='send_gift'),
    path('<uuid:stream_id>/stats/',           views.stream_stats, name='stats'),
]