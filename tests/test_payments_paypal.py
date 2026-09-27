from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth import get_user_model
from subscriptions.models import SubscriptionPlan, Subscription
from payments.models import Payment
from payments.services import PaymentService

User = get_user_model()


class PayPalPaymentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='paypal_user@humatron.me',
            email='paypal_user@humatron.me',
            password='StrongPassword123!',
            is_active=True,
            is_email_verified=True
        )
        self.plan = SubscriptionPlan.objects.create(
            name='Professional',
            code='professional',
            price=Decimal('50.00'),
            currency='USD',
            price_etb=Decimal('6750.00'),
            duration_days=30,
            pdf_limit=25
        )

    def test_successful_paypal_order_activates_subscription(self):
        order_id = "PAYPAL-ORDER-SUCCESS-001"
        success, msg, payment = PaymentService.verify_and_activate_paypal(
            user=self.user,
            plan=self.plan,
            order_id=order_id
        )
        self.assertTrue(success)
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, Payment.STATUS_VERIFIED)
        self.assertEqual(payment.amount, Decimal('50.00'))

        # Verify subscription was activated
        self.assertIsNotNone(payment.subscription)
        self.assertEqual(payment.subscription.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(payment.subscription.user, self.user)
        self.assertEqual(payment.subscription.pdf_limit, 25)

    def test_duplicate_paypal_transaction_rejected(self):
        order_id = "PAYPAL-ORDER-DUP-001"
        success1, _, _ = PaymentService.verify_and_activate_paypal(self.user, self.plan, order_id)
        self.assertTrue(success1)

        # Second attempt with same transaction ID must fail (Section 27 idempotency)
        success2, msg2, _ = PaymentService.verify_and_activate_paypal(self.user, self.plan, order_id)
        self.assertFalse(success2)
        self.assertIn("already been processed", msg2)
        self.assertEqual(Subscription.objects.filter(user=self.user, status=Subscription.STATUS_ACTIVE).count(), 1)

    @patch('payments.paypal_service.PayPalService.verify_and_capture_order')
    def test_underpaid_paypal_order_rejected(self, mock_capture):
        mock_capture.return_value = (False, "Underpaid: expected 50.00, received 25.00", None)
        success, msg, payment = PaymentService.verify_and_activate_paypal(
            user=self.user,
            plan=self.plan,
            order_id="UNDERPAID-ORDER-001"
        )
        self.assertFalse(success)
        self.assertIn("Underpaid", msg)
        self.assertFalse(Subscription.objects.filter(user=self.user, status=Subscription.STATUS_ACTIVE).exists())

    @patch('payments.paypal_service.PayPalService.verify_and_capture_order')
    def test_currency_mismatch_paypal_rejected(self, mock_capture):
        mock_capture.return_value = (False, "Currency mismatch: expected USD, got EUR", None)
        success, msg, payment = PaymentService.verify_and_activate_paypal(
            user=self.user,
            plan=self.plan,
            order_id="WRONG-CURRENCY-ORDER-001"
        )
        self.assertFalse(success)
        self.assertIn("Currency mismatch", msg)
