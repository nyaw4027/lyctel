"""
delivery/signals.py

Creates a RiderEarning row the moment a Delivery transitions to DELIVERED —
so rider earnings are recorded automatically regardless of who (staff view,
rider app, admin, webhook) marks the delivery done.

Register in delivery/apps.py (see below).
"""
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from .models import Delivery


@receiver(pre_save, sender=Delivery)
def _stash_prev_delivery_status(sender, instance, **kwargs):
    """Stash the current DB status before the save so post_save can detect transitions."""
    if instance.pk:
        instance._prev_delivery_status = (
            Delivery.objects.filter(pk=instance.pk)
            .values_list('status', flat=True)
            .first()
        )
    else:
        instance._prev_delivery_status = None


@receiver(post_save, sender=Delivery)
def _create_rider_earning_on_delivery(sender, instance, created, **kwargs):
    """
    Creates a RiderEarning record the first time a Delivery status
    transitions to DELIVERED.

    Design notes:
    - Uses get_or_create so re-saving a delivered delivery (e.g. admin
      touching it) doesn't create duplicate earning rows.
    - rider_commission is already calculated in Delivery.save() via
      calculate_commission(), so we just read it here — no re-calculation.
    - Only fires when there IS a rider assigned; system-assigned deliveries
      with no rider (edge cases) are skipped safely.
    """
    prev    = getattr(instance, '_prev_delivery_status', None)
    current = instance.status

    just_delivered = (
        current == Delivery.Status.DELIVERED
        and prev  != Delivery.Status.DELIVERED
    )

    if not just_delivered:
        return

    if not instance.rider:
        return

    from rider.models import RiderEarning

    RiderEarning.objects.get_or_create(
        delivery=instance,
        defaults={
            'rider':  instance.rider,
            'amount': instance.rider_commission,
            'status': RiderEarning.Status.PENDING,
        }
    )