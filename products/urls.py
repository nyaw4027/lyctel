from django.urls import path
from . import views

app_name = 'products'

urlpatterns = [
    path('',                        views.product_list,        name='list'),
    path('deals/',                  views.deals_page,          name='deals'),
    # Search autocomplete — called by frontend with 300ms debounce
    # Returns JSON: {"results": [{"type": "product", "label": "...", "url": "..."}]}
    path('autocomplete/',           views.search_autocomplete, name='autocomplete'),
    path('<slug:slug>/',            views.product_detail,      name='detail'),
    path('video/<int:pk>/delete/',  views.video_delete,        name='video_delete'),
]