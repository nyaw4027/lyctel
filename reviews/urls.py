from django.urls import path
from . import views

app_name = 'reviews'

urlpatterns = [
    path('product/<int:product_id>/review/',        views.submit_review, name='submit'),
    path('review/<int:review_id>/delete/',          views.delete_review, name='delete'),
]