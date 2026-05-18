# accounts/signals.py
from django.contrib.auth.signals import user_logged_in
from cart.views import merge_guest_cart

def merge_cart_on_login(sender, user, request, **kwargs):
    merge_guest_cart(request, user)

user_logged_in.connect(merge_cart_on_login)


from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.apps import apps

from ecommerce.models import User


@receiver(pre_save, sender=User)
def track_role_change(sender, instance, **kwargs):
    """Capture the old role before saving so we can detect a change."""
    if instance.pk:
        try:
            instance._old_role = User.objects.get(pk=instance.pk).role
        except User.DoesNotExist:
            instance._old_role = None
    else:
        instance._old_role = None   # brand-new user


@receiver(post_save, sender=User)
def create_rider_profile_on_role_change(sender, instance, created, **kwargs):
    """
    Create a RiderProfile whenever:
      - A new user is saved with role=rider, OR
      - An existing user's role is changed to rider.
    Idempotent: skips silently if the profile already exists.
    """
    if instance.role != User.Role.RIDER:
        return

    RiderProfile = apps.get_model('rider', 'RiderProfile')

    old_role = getattr(instance, '_old_role', None)
    role_just_became_rider = created or (old_role != User.Role.RIDER)

    if role_just_became_rider:
        RiderProfile.objects.get_or_create(rider=instance)