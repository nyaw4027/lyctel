"""Tests for the Hubtel checkout webhook / confirmation flow."""
import json
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from order.models import Order
from payment.hubtel import HubtelCheckout


def _callback(ref, amount=100.0, code='0000', status='Success', checkout_id='chk_1'):
    return {
        'ResponseCode': code,
        'Status': status,
        'Data': {
            'CheckoutId': checkout_id,
            'ClientReference': ref,
            'Status': status,
            'Amount': amount,
            'TransactionId': 'TXN123',
        },
    }


@override_settings(HUBTEL_CLIENT_ID='id', HUBTEL_CLIENT_SECRET='secret',
                   HUBTEL_MERCHANT_ACCT='123456')
class HubtelWebhookTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            **{User.USERNAME_FIELD: 'buyer@example.com'}, password='pw12345!')
        self.order = Order.objects.create(customer=self.user, total_amount=Decimal('100.00'))
        base = self.order.order_ref[4:]            # strip "ORD-"
        self.ref = f'{base}-A1B2C3'               # what initiate() sends
        self.order.hubtel_reference = self.ref
        self.order.save(update_fields=['hubtel_reference'])
        self.url = reverse('payment:hubtel_webhook')

        # Keep side effects out of the unit under test.
        for target in ('payment.views._split_and_disburse',):
            p = mock.patch(target)
            p.start()
            self.addCleanup(p.stop)

    def post(self, body):
        return self.client.post(self.url, data=json.dumps(body),
                                content_type='application/json')

    def _verify(self, **ret):
        return mock.patch.object(HubtelCheckout, 'verify', return_value=ret)

    def test_webhook_marks_order_paid_when_status_api_confirms(self):
        with self._verify(paid=True, status='paid', amount=100.0, transaction_id='T1'):
            self.post(_callback(self.ref))
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)

    def test_order_found_from_older_reference(self):
        """Customer paid on an earlier checkout after pressing 'Try again'."""
        old_ref = f'{self.order.order_ref[4:]}-FFFFFF'
        with self._verify(paid=True, status='paid', amount=100.0):
            self.post(_callback(old_ref))
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)

    def test_forged_callback_rejected_when_hubtel_says_unpaid(self):
        with self._verify(paid=False, status='unpaid'):
            self.post(_callback(self.ref))
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.UNPAID)

    def test_underpayment_rejected(self):
        with self._verify(paid=True, status='paid', amount=1.0):
            self.post(_callback(self.ref, amount=1.0))
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.UNPAID)

    def test_fallback_to_callback_when_status_api_unreachable(self):
        with self._verify(paid=False, status='http_403'):
            self.post(_callback(self.ref))
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)

    @override_settings(HUBTEL_REQUIRE_STATUS_CHECK=True)
    def test_strict_mode_needs_status_api(self):
        with self._verify(paid=False, status='http_403'):
            self.post(_callback(self.ref))
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.UNPAID)

    def test_failed_callback_does_not_mark_paid(self):
        with self._verify(paid=False, status='http_403'):
            self.post(_callback(self.ref, code='2001', status='Failed'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.UNPAID)

    def test_mark_paid_runs_side_effects_once(self):
        from payment import views
        with mock.patch('payment.views._split_and_disburse') as split:
            views._mark_paid(self.order, 'T1')
            views._mark_paid(Order.objects.get(pk=self.order.pk), 'T1')
        self.assertEqual(split.call_count, 1)

    def test_status_poll_confirms_when_webhook_missed(self):
        self.client.force_login(self.user)
        with self._verify(paid=True, status='paid', amount=100.0):
            resp = self.client.get(reverse('payment:hubtel_status',
                                           args=[self.order.order_ref]))
        self.assertTrue(resp.json()['paid'])


class HubtelHelperTests(TestCase):
    def test_parse_callback_requires_success_status(self):
        self.assertFalse(HubtelCheckout.parse_callback(
            _callback('X', code='0000', status='Failed'))['paid'])
        self.assertTrue(HubtelCheckout.parse_callback(_callback('X'))['paid'])

    def test_order_urls_point_at_real_routes(self):
        order = Order(order_ref='ORD-ABC123')
        req = RequestFactory().get('/', HTTP_HOST='testserver')
        cb, ret, cancel = HubtelCheckout._order_urls(order, req)
        self.assertTrue(cb.endswith(reverse('payment:hubtel_webhook')))
        self.assertIn(reverse('payment:processing'), ret)
        self.assertIn('ORD-ABC123', ret)
        self.assertIn(reverse('payment:hubtel_cancel'), cancel)
