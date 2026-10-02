from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from subscriptions.models import SubscriptionPlan, Subscription
from subscriptions.services import PricingCalculator
from payments.models import Payment, TelebirrPaymentSettings, BinanceManualPaymentSettings
from payments.services import PaymentService

User = get_user_model()


class TelebirrPlansAdminAndSubmissionTests(TestCase):
    """
    Test suite for:
    1. Telebirr plans: Free (0 ETB), 200 ETB (Basic), 300 ETB (Pro), 500 ETB (Unlimited)
    2. Admin page for Telebirr: Admin can configure Name and Phone number
    3. User flow: Upload transaction number upon completion
    4. Admin approval of Telebirr payment in Django Admin
    5. Binance: Only transaction number is necessary, not screenshot
    """

    def setUp(self):
        self.client = Client()

        # Admin user
        self.admin = User.objects.create_superuser(
            username='admin@humatron.me',
            email='admin@humatron.me',
            password='AdminPassword123!'
        )

        # Ethiopian customer
        self.user = User.objects.create_user(
            username='ethiopian_customer@humatron.me',
            email='ethiopian_customer@humatron.me',
            password='CustomerPassword123!',
            country='Ethiopia',
            is_active=True,
            is_email_verified=True
        )

        # 4 Subscription Plans with ETB pricing
        self.free_plan, _ = SubscriptionPlan.objects.update_or_create(
            slug='free',
            defaults={
                'name': 'Free',
                'code': 'free',
                'price': Decimal('0.00'),
                'price_etb': Decimal('0.00'),
                'currency': 'USD',
                'billing_period': 'month',
                'usage_limit': 5,
                'max_file_size': 10,
                'active': True,
                'sort_order': 1
            }
        )
        self.basic_plan, _ = SubscriptionPlan.objects.update_or_create(
            slug='basic',
            defaults={
                'name': 'Basic',
                'code': 'basic',
                'price': Decimal('18.00'),
                'price_etb': Decimal('400.00'),
                'currency': 'USD',
                'billing_period': 'month',
                'usage_limit': 50,
                'max_file_size': 50,
                'active': True,
                'sort_order': 2
            }
        )
        self.pro_plan, _ = SubscriptionPlan.objects.update_or_create(
            slug='pro',
            defaults={
                'name': 'Pro',
                'code': 'pro',
                'price': Decimal('48.00'),
                'price_etb': Decimal('600.00'),
                'currency': 'USD',
                'billing_period': 'month',
                'usage_limit': 200,
                'max_file_size': 100,
                'active': True,
                'sort_order': 3
            }
        )
        self.unlimited_plan, _ = SubscriptionPlan.objects.update_or_create(
            slug='unlimited',
            defaults={
                'name': 'Unlimited',
                'code': 'unlimited',
                'price': Decimal('90.00'),
                'price_etb': Decimal('1000.00'),
                'currency': 'USD',
                'billing_period': 'month',
                'usage_limit': 0,
                'max_file_size': 250,
                'active': True,
                'sort_order': 4
            }
        )

        # Telebirr Settings
        self.telebirr_settings = TelebirrPaymentSettings.get_settings()
        self.telebirr_settings.receiver_name = "Humatron Technologies"
        self.telebirr_settings.phone_number = "0911223344"
        self.telebirr_settings.enabled = True
        self.telebirr_settings.save()

    def test_telebirr_plans_etb_pricing(self):
        """Verify the 4 Telebirr plans have exact prices: Free (0 ETB), 400 ETB, 600 ETB, 1000 ETB."""
        p_free = PricingCalculator.calculate(self.free_plan, self.user)
        self.assertEqual(p_free['final_etb'], Decimal('0.00'))

        p_basic = PricingCalculator.calculate(self.basic_plan, self.user)
        self.assertEqual(p_basic['final_etb'], Decimal('400.00'))

        p_pro = PricingCalculator.calculate(self.pro_plan, self.user)
        self.assertEqual(p_pro['final_etb'], Decimal('600.00'))

        p_unlimited = PricingCalculator.calculate(self.unlimited_plan, self.user)
        self.assertEqual(p_unlimited['final_etb'], Decimal('1000.00'))

    def test_ethiopian_user_sees_etb_plans_on_pricing_page(self):
        """Authenticated Ethiopian user sees Free, 400 ETB, 600 ETB, and 1000 ETB on plans page."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('subscriptions:plans'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn("Free (Telebirr)", content)
        self.assertIn("400 ETB (Telebirr)", content)
        self.assertIn("600 ETB (Telebirr)", content)
        self.assertIn("1000 ETB (Telebirr)", content)

    def test_admin_configures_telebirr_name_and_phone(self):
        """Admin can configure Name and Phone Number in TelebirrPaymentSettings in admin."""
        self.telebirr_settings.receiver_name = "Abebe Bikila"
        self.telebirr_settings.phone_number = "0922334455"
        self.telebirr_settings.save()

        self.client.force_login(self.user)
        response = self.client.get(reverse('payments:checkout', args=['basic']))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn("Abebe Bikila", content)
        self.assertIn("0922334455", content)
        self.assertIn("400.00 ETB", content)

    def test_telebirr_user_uploads_transaction_number_upon_completion(self):
        """User submits only their transaction number upon completing Telebirr payment."""
        self.client.force_login(self.user)
        url = reverse('payments:verify_telebirr', args=['basic'])

        # User submits only their transaction number
        response = self.client.post(url, {
            'transaction_id': 'TB-TX-99887766',
        })
        self.assertRedirects(response, reverse('accounts:dashboard'))

        # Payment record is created in PENDING status for admin review
        payment = Payment.objects.filter(transaction_id='TB-TX-99887766').first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.user, self.user)
        self.assertEqual(payment.plan, self.basic_plan)
        self.assertEqual(payment.amount, Decimal('400.00'))
        self.assertEqual(payment.currency, 'ETB')
        self.assertEqual(payment.status, Payment.STATUS_PENDING)
        self.assertEqual(payment.provider, Payment.PROVIDER_TELEBIRR)

    def test_admin_approves_telebirr_payment_and_activates_subscription(self):
        """Admin reviews and approves Telebirr payment in Django Admin, activating subscription."""
        # Create pending payment
        payment = Payment.objects.create(
            user=self.user,
            provider=Payment.PROVIDER_TELEBIRR,
            payment_method=Payment.METHOD_TELEBIRR,
            transaction_id='TB-TX-APPROVE-1',
            plan=self.pro_plan,
            amount=Decimal('600.00'),
            currency='ETB',
            status=Payment.STATUS_PENDING,
            payment_country='Ethiopia',
            original_amount=Decimal('600.00'),
            final_amount=Decimal('600.00'),
        )

        success, msg, _ = PaymentService.approve_telebirr_payment(payment, self.admin)
        self.assertTrue(success)

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.STATUS_APPROVED)
        self.assertEqual(payment.reviewed_by, self.admin)
        self.assertIsNotNone(payment.subscription)

        # User now has active Pro subscription
        sub = Subscription.objects.filter(user=self.user, status=Subscription.STATUS_ACTIVE).first()
        self.assertIsNotNone(sub)
        self.assertEqual(sub.plan, self.pro_plan)

    def test_binance_only_transaction_number_necessary_no_screenshot(self):
        """In Binance, only transaction number is necessary, not screenshot."""
        non_eth_user = User.objects.create_user(
            username='uk_customer@humatron.me',
            email='uk_customer@humatron.me',
            password='Password123!',
            country='United Kingdom',
            is_active=True,
            is_email_verified=True
        )
        self.client.force_login(non_eth_user)

        # Checkout page states screenshot is not required
        checkout_page = self.client.get(reverse('payments:binance_manual_checkout', args=['pro']))
        self.assertEqual(checkout_page.status_code, 200)
        content = checkout_page.content.decode('utf-8')
        self.assertIn("Only your Binance Transaction Number is necessary", content)
        self.assertIn("screenshot is not required", content.lower())

        # Submission with ONLY transaction number succeeds
        response = self.client.post(reverse('payments:binance_manual_checkout', args=['pro']), {
            'transaction_id': 'BINANCE-TX-NO-SCREENSHOT-99',
        })
        payment = Payment.objects.filter(transaction_id='BINANCE-TX-NO-SCREENSHOT-99').first()
        self.assertIsNotNone(payment)
        self.assertFalse(bool(payment.proof_file))  # No screenshot uploaded
        self.assertEqual(payment.status, Payment.STATUS_PENDING)
        self.assertEqual(payment.amount, Decimal('48.00'))  # Pro plan doubled price
        self.assertRedirects(response, reverse('payments:binance_manual_status', args=[payment.id]))

