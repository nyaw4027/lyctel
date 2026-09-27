"""Tests for the Hubtel food-order payment flow."""
import json
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from food.models import FoodOrder, FoodPayment
from payment.hubtel import HubtelCheckout


def _callback(ref, amount=50.0, code='0000', status='Success'):
    return {'ResponseCode': code, 'Status': status,
            'Data': {'ClientReference': ref, 'Status': status, 'Amount': amount,
                     'CheckoutId': 'chk_food', 'TransactionId': 'TXN9'}}


@override_settings(HUBTEL_CLIENT_ID='id', HUBTEL_CLIENT_SECRET='secret',
                   HUBTEL_MERCHANT_ACCT='123456')
class FoodHubtelTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user(
            **{User.USERNAME_FIELD: 'eater@example.com'}, password='pw12345!')
        self.order = FoodOrder.objects.create(
            customer=self.user, delivery_address='Somewhere', delivery_phone='0241234567',
            subtotal=Decimal('45.00'), delivery_fee=Decimal('5.00'),
            total_amount=Decimal('50.00'))
        p = mock.patch('delivery.services.auto_assign_for_food_order', create=True)
        p.start()
        self.addCleanup(p.stop)

    def _hubtel_response(self):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {'responseCode': '0000', 'data': {
            'checkoutUrl': 'https://pay.hubtel.com/food1',
            'checkoutDirectUrl': 'https://pay.hubtel.com/food1/direct',
            'checkoutId': 'chk_food'}}
        return resp

    def _initiate(self):
        self.client.force_login(self.user)
        with mock.patch('payment.hubtel.requests.post',
                        return_value=self._hubtel_response()) as post:
            resp = self.client.get(reverse('food:payment_initiate',
                                           args=[self.order.order_ref]))
        return resp, post

    def test_initiate_reads_nested_checkout_url_and_redirects(self):
        resp, post = self._initiate()
        self.assertContains(resp, 'https://pay.hubtel.com/food1')
        self.assertNotContains(resp, '<iframe')
        payload = post.call_args.kwargs['json']
        self.assertTrue(payload['callbackUrl'].endswith(reverse('food:payment_webhook')))
        fp = FoodPayment.objects.get(food_order=self.order)
        self.assertEqual(fp.transaction_id, payload['clientReference'])
        self.assertEqual(fp.gateway_ref, 'chk_food')

    def test_retry_uses_new_reference(self):
        _, first = self._initiate()
        _, second = self._initiate()
        self.assertNotEqual(first.call_args.kwargs['json']['clientReference'],
                            second.call_args.kwargs['json']['clientReference'])
        self.assertEqual(FoodPayment.objects.filter(food_order=self.order).count(), 1)

    def _webhook(self, body, **verify):
        with mock.patch.object(HubtelCheckout, 'verify', return_value=verify):
            return self.client.post(reverse('food:payment_webhook'),
                                    data=json.dumps(body), content_type='application/json')

    def test_webhook_marks_paid_once_verified(self):
        self._initiate()
        ref = FoodPayment.objects.get(food_order=self.order).transaction_id
        self._webhook(_callback(ref), paid=True, status='paid', amount=50.0)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, FoodOrder.PaymentStatus.PAID)

    def test_forged_webhook_rejected(self):
        self._initiate()
        ref = FoodPayment.objects.get(food_order=self.order).transaction_id
        self._webhook(_callback(ref), paid=False, status='unpaid')
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.payment_status, FoodOrder.PaymentStatus.PAID)

    def test_underpaid_webhook_rejected(self):
        self._initiate()
        ref = FoodPayment.objects.get(food_order=self.order).transaction_id
        self._webhook(_callback(ref, amount=1.0), paid=False, status='http_403')
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.payment_status, FoodOrder.PaymentStatus.PAID)

    def test_webhook_for_older_attempt_still_found(self):
        self._initiate()
        old_ref = f'{self.order.order_ref}-AAAAAA'
        self._webhook(_callback(old_ref), paid=True, status='paid', amount=50.0)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, FoodOrder.PaymentStatus.PAID)

    def test_status_poll_confirms_missed_webhook(self):
        self._initiate()
        with mock.patch.object(HubtelCheckout, 'verify',
                               return_value={'paid': True, 'status': 'paid', 'amount': 50.0}):
            resp = self.client.get(reverse('food:payment_status', args=[self.order.order_ref]))
        self.assertTrue(resp.json()['paid'])

    def test_mark_paid_is_idempotent(self):
        from food import views
        self._initiate()
        fp = FoodPayment.objects.get(food_order=self.order)
        with mock.patch('delivery.services.auto_assign_for_food_order', create=True) as assign:
            views._mark_food_paid(fp, self.order, 'T', {})
            views._mark_food_paid(FoodPayment.objects.get(pk=fp.pk), self.order, 'T', {})
        self.assertEqual(assign.call_count, 1)


class PushNotifyTests(TestCase):
    def test_send_push_queries_subscriptions(self):
        from ecommerce.models import PushSubscription
        from push_notify import send_push_notification
        User = get_user_model()
        user = User.objects.create_user(
            **{User.USERNAME_FIELD: 'push@example.com'}, password='pw12345!')
        PushSubscription.objects.create(user=user, endpoint='https://push.example/1',
                                        p256dh='k', auth='a')
        with mock.patch('push_notify._send_to_subscription', return_value=True) as send:
            self.assertEqual(send_push_notification(user, 'T', 'B'), 1)
        send.assert_called_once()
