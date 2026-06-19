"""
notifications.py — Place this file at the project root (same level as manage.py)
or inside a shared app like ecommerce/notifications.py

Handles SMS via Termii and in-app notifications for:
- Order status changes (product orders)
- Food order status changes
- Rider assignment
"""

import requests
from django.conf import settings


# ── TERMII SMS ────────────────────────────────────────────────────────────────

TERMII_API_URL = 'https://v3.api.termii.com/api/sms/send'
SENDER_ID      = 'Lynctel'   # Must be approved in Termii dashboard


def _format_gh_number(phone):
    """Convert 024XXXXXXX → 23324XXXXXXX for Termii."""
    phone = str(phone).strip().replace(' ', '').replace('-', '')
    if phone.startswith('0'):
        return '233' + phone[1:]
    if phone.startswith('+'):
        return phone[1:]
    return phone


def send_sms(phone, message):
    """
    Send an SMS via Termii.
    Add TERMII_API_KEY to your .env and Railway variables.
    """
    api_key = getattr(settings, 'TERMII_API_KEY', '')
    if not api_key:
        return False  # Silently skip if not configured

    try:
        resp = requests.post(
            TERMII_API_URL,
            json={
                'to':      _format_gh_number(phone),
                'from':    SENDER_ID,
                'sms':     message,
                'type':    'plain',
                'channel': 'generic',
                'api_key': api_key,
            },
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


# ── ORDER STATUS SMS TEMPLATES ────────────────────────────────────────────────

def sms_order_confirmed(order):
    return send_sms(
        order.delivery_phone,
        f"Hi! Your Lynctel order {order.order_ref} has been confirmed. "
        f"Total: GHS {order.total_amount}. We'll notify you when it's on the way. "
        f"Track: lynctel.up.railway.app/orders/{order.order_ref}/track/"
    )


def sms_order_dispatched(order, rider_name=None, rider_phone=None):
    rider_info = ''
    if rider_name:
        rider_info = f" Your rider is {rider_name}"
        if rider_phone:
            rider_info += f" ({rider_phone})"
        rider_info += '.'
    return send_sms(
        order.delivery_phone,
        f"Your Lynctel order {order.order_ref} is on the way!{rider_info} "
        f"Please be available at {order.delivery_address}."
    )


def sms_order_delivered(order):
    return send_sms(
        order.delivery_phone,
        f"Your Lynctel order {order.order_ref} has been delivered! "
        f"Thank you for shopping with us. "
        f"Rate your experience: lynctel.up.railway.app/products/"
    )


def sms_order_cancelled(order):
    return send_sms(
        order.delivery_phone,
        f"Your Lynctel order {order.order_ref} has been cancelled. "
        f"Contact us on WhatsApp: +233558040216 for help."
    )


# ── FOOD ORDER SMS TEMPLATES ──────────────────────────────────────────────────

def sms_food_confirmed(food_order):
    return send_sms(
        food_order.delivery_phone,
        f"Your food order {food_order.order_ref} from {food_order.vendor.name} "
        f"is confirmed! Estimated delivery: {food_order.estimated_delivery_time} mins. "
        f"Total: GHS {food_order.total_amount}."
    )


def sms_food_preparing(food_order):
    return send_sms(
        food_order.delivery_phone,
        f"Your order {food_order.order_ref} is being prepared by {food_order.vendor.name}. "
        f"A rider will pick it up shortly!"
    )


def sms_food_dispatched(food_order, rider_name=None, rider_phone=None):
    rider_info = f" Rider: {rider_name} ({rider_phone})." if rider_name else ''
    return send_sms(
        food_order.delivery_phone,
        f"Your food order {food_order.order_ref} is on the way!{rider_info} "
        f"Delivering to: {food_order.delivery_address}."
    )


def sms_food_delivered(food_order):
    return send_sms(
        food_order.delivery_phone,
        f"Your food order {food_order.order_ref} from {food_order.vendor.name} "
        f"has been delivered! Enjoy your meal. 😋"
    )


# ── RIDER SMS ─────────────────────────────────────────────────────────────────

def sms_rider_assigned(delivery):
    """Notify rider via SMS when assigned a delivery."""
    try:
        rider_phone = delivery.rider.rider.phone

        order_ref = ''
        dropoff   = delivery.dropoff_location or 'See dashboard'
        if delivery.order:
            order_ref = delivery.order.order_ref
        elif hasattr(delivery, 'food_order') and delivery.food_order:
            order_ref = delivery.food_order.order_ref

        return send_sms(
            rider_phone,
            f"New delivery assigned! Order: {order_ref}. "
            f"Pickup: {delivery.pickup_location or 'Vendor'}. "
            f"Dropoff: {dropoff}. "
            f"Commission: GHS {delivery.rider_commission}. "
            f"Open app: lynctel.up.railway.app/rider/"
        )
    except Exception:
        return False


# ── TRIGGER FUNCTIONS (call these from views/services) ────────────────────────

def notify_order_status_change(order, new_status):
    """
    Call this whenever an order status changes.
    Hook into dashboard/views.py order_detail POST action == 'update_status'
    """
    try:
        if new_status == 'confirmed':
            sms_order_confirmed(order)
        elif new_status == 'dispatched':
            delivery = getattr(order, 'delivery', None)
            rider_name = rider_phone = None
            if delivery and delivery.rider:
                rider_name  = delivery.rider.rider.get_full_name()
                rider_phone = delivery.rider.rider.phone
            sms_order_dispatched(order, rider_name, rider_phone)
        elif new_status == 'delivered':
            sms_order_delivered(order)
        elif new_status == 'cancelled':
            sms_order_cancelled(order)
    except Exception:
        pass  # Never crash order flow


def notify_food_order_status_change(food_order, new_status):
    """
    Call this whenever a FoodOrder status changes.
    Hook into food/views.py restaurant_update_order
    """
    try:
        if new_status == 'confirmed':
            sms_food_confirmed(food_order)
        elif new_status == 'preparing':
            sms_food_preparing(food_order)
        elif new_status in ('ready', 'picked_up', 'en_route'):
            delivery = getattr(food_order, 'delivery', None)
            rider_name = rider_phone = None
            if delivery and delivery.rider:
                rider_name  = delivery.rider.rider.get_full_name()
                rider_phone = delivery.rider.rider.phone
            sms_food_dispatched(food_order, rider_name, rider_phone)
        elif new_status == 'delivered':
            sms_food_delivered(food_order)
    except Exception:
        pass