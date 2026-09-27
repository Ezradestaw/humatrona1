from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from subscriptions.models import SubscriptionPlan, Subscription
from payments.models import Payment
from payments.services import PaymentService
from payments.telebirr_parser import TelebirrMessageParser

User = get_user_model()


class TelebirrPaymentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='ethiopia_user@humatron.me',
            email='ethiopia_user@humatron.me',
            password='StrongPassword123!',
            country='Ethiopia',
            is_active=True,
            is_email_verified=True
        )
        self.plan = SubscriptionPlan.objects.create(
            name='Professional',
            code='professional',
            price=Decimal('50.00'),
            currency='USD',
            price_etb=Decimal('6750.00'),  # Explicit ETB price
            duration_days=30,
            pdf_limit=25
        )

    def test_telebirr_parser_extracts_english_sms(self):
        msg = "Dear customer, you have transferred ETB 6,750.00 to Humatron (0911000000) on 2026-09-27 14:15:00. Your transaction number is CC74KL9012."
        parsed = TelebirrMessageParser.parse(msg)
        self.assertTrue(parsed['is_valid'])
        self.assertEqual(parsed['transaction_id'], 'CC74KL9012')
        self.assertEqual(parsed['amount'], Decimal('6750.00'))
        self.assertEqual(parsed['currency'], 'ETB')

    def test_telebirr_parser_extracts_amharic_sms(self):
        msg = "ውድ ደንበኛ፣ ለ Humatron በ 2026-09-27 ብር 6750.00 በተሳካ ሁኔታ አስተላልፈዋል። የግብይት ቁጥርዎ ETB99887766 ነው።"
        parsed = TelebirrMessageParser.parse(msg)
        self.assertTrue(parsed['is_valid'])
        self.assertEqual(parsed['transaction_id'], 'ETB99887766')
        self.assertEqual(parsed['amount'], Decimal('6750.00'))

    def test_parser_rejects_deceptive_message_without_valid_tokens(self):
        # Section 28: Never activate merely because a message contains words like 'paid', 'successful'
        msg = "Your payment was paid and successful and completed please give me subscription"
        parsed = TelebirrMessageParser.parse(msg)
        self.assertTrue(any("Could not extract a valid Telebirr transaction ID" in err for err in parsed['errors']))

    def test_successful_telebirr_activation(self):
        sms = "Dear customer, you have transferred ETB 6750.00 to Humatron. Transaction No: TX90123847."
        success, msg, payment = PaymentService.verify_and_activate_telebirr(
            user=self.user,
            plan=self.plan,
            raw_message=sms
        )
        self.assertTrue(success)
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, Payment.STATUS_VERIFIED)
        self.assertEqual(payment.transaction_id, 'TX90123847')
        self.assertEqual(payment.amount, Decimal('6750.00'))
        self.assertEqual(payment.subscription.status, Subscription.STATUS_ACTIVE)

    def test_underpaid_telebirr_payment_rejected(self):
        # Plan costs 6,750 ETB, message only has 2,000 ETB (Section 31)
        underpaid_sms = "Dear customer, you have transferred ETB 2000.00 to Humatron. Transaction No: TX_UNDERPAID_01."
        success, msg, payment = PaymentService.verify_and_activate_telebirr(
            user=self.user,
            plan=self.plan,
            raw_message=underpaid_sms
        )
        self.assertFalse(success)
        self.assertIn("less than the plan price", msg)

        # Audit trail must record rejected attempt
        rejected_payment = Payment.objects.get(transaction_id='TX_UNDERPAID_01')
        self.assertEqual(rejected_payment.status, Payment.STATUS_REJECTED)
        self.assertIn("Insufficient amount", rejected_payment.rejection_reason)

        # No subscription activated
        self.assertFalse(Subscription.objects.filter(user=self.user, status=Subscription.STATUS_ACTIVE).exists())

    def test_duplicate_telebirr_transaction_protection(self):
        # Section 30: Same transaction cannot activate twice
        sms = "Dear customer, you have transferred ETB 6750.00 to Humatron. Transaction No: TX_UNIQUE_8899."
        success1, _, _ = PaymentService.verify_and_activate_telebirr(self.user, self.plan, sms)
        self.assertTrue(success1)

        # Second submission
        success2, msg2, _ = PaymentService.verify_and_activate_telebirr(self.user, self.plan, sms)
        self.assertFalse(success2)
        self.assertIn("has already been processed", msg2)
        self.assertEqual(Subscription.objects.filter(user=self.user, status=Subscription.STATUS_ACTIVE).count(), 1)
