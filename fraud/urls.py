from django.urls import path
from . import views

app_name = 'fraud'

urlpatterns = [
    path('review/',                  views.flagged_orders, name='flagged_orders'),
    path('review/<int:pk>/resolve/', views.resolve_flag,   name='resolve_flag'),
]