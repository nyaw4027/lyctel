# accounts/signals.py
from django.contrib.auth.signals import user_logged_in
from cart.views import merge_guest_cart

def merge_cart_on_login(sender, user, request, **kwargs):
    merge_guest_cart(request, user)

user_logged_in.connect(merge_cart_on_login)