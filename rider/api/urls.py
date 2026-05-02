from django.urls import path
from .views import active_deliveries

urlpatterns = [
    path("active/", active_deliveries),
]