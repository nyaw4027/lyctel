"""
Hooks fraud checks into the moment an order's payment is confirmed —
without requiring ANY changes to the payment app for the address/phone
velocity checks. We detect the transition to PaymentStatus.PAID directly
on the Order model via pre_save/post_save:

  1. pre_save stashes the order's payment_status as it currently exists
     in the database (before this save), on the instance itself.
  2. post_save compares that stashed value to the new value — if it just
     became PAID, run the checks.

This only touches order/models.py's Order — nothing in payment/ needs to
change for this part. (Card testing detection is the one rule that still
needs the payment app to call fraud.services.record_payment_attempt() —
see that function's docstring.)
"""
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from order.models import Order
from .services import run_fraud_checks


@receiver(pre_save, sender=Order)
def _stash_previous_payment_status(sender, instance, **kwargs):
    if instance.pk:
        instance._fraud_prev_payment_status = (
            Order.objects.filter(pk=instance.pk)
            .values_list('payment_status', flat=True)
            .first()
        )
    else:
        instance._fraud_prev_payment_status = None


@receiver(post_save, sender=Order)
def _check_fraud_on_payment_confirmed(sender, instance, created, **kwargs):
    prev = getattr(instance, '_fraud_prev_payment_status', None)
    just_became_paid = (
        instance.payment_status == Order.PaymentStatus.PAID and prev != Order.PaymentStatus.PAID
    )
    if just_became_paid:
        run_fraud_checks(instance)