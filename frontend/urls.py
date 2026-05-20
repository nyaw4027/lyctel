
from django.urls import path
from . import views
app_name = 'frontend'
urlpatterns = [
    path('', views.home, name='home'),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path('how-it-works/', views.how_it_works, name='how_it_works'),

    path('privacy-policy/', views.privacy_policy, name='privacy_policy'),
    path('terms/', views.terms, name='terms'),
    path('cookies/', views.cookies, name='cookies'),
]