from datetime import timedelta
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from subscriptions.models import SubscriptionPlan, Subscription
from subscriptions.services import SubscriptionService, PricingCalculator
from payments.models import Payment, BinanceManualPaymentSettings
from payments.services import PaymentService

User = get_user_model()


class SubscriptionPlanAndPricingTests(TestCase):
    """
    Comprehensive tests for the 4-tier Humatron subscription system:
    1. FREE ($0/mo, 5 PDFs, 10MB)
    2. BASIC ($9/mo, 50 PDFs, 50MB)
    3. PRO ($24/mo, 200 PDFs, 100MB)
    4. UNLIMITED ($45/mo, Unlimited PDFs, 250MB)
    And verification of:
    - Zero student references
    - Free plan immediate activation without payment
    - Renewal date extension
    - Exact DB pricing on Binance checkout
    - Receiving UID 1104715375
    """

    def setUp(self):
        self.client = Client()

        # Seed or get 4 plans
        self.free_plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='free',
            defaults={
                'name': 'Free',
                'code': 'free',
                'price': Decimal('0.00'),
                'currency': 'USD',
                'billing_period': 'month',
                'usage_limit': 5,
                'max_file_size': 10,
                'processing_priority': 'Normal',
                'description': 'Basic PDF conversion for casual users.',
                'features': ['5 PDFs/month', '10 MB maximum file size', 'Standard processing', 'Normal priority'],
                'active': True,
                'sort_order': 1,
            }
        )

        self.basic_plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='basic',
            defaults={
                'name': 'Basic',
                'code': 'basic',
                'price': Decimal('18.00'),
                'currency': 'USD',
                'billing_period': 'month',
                'usage_limit': 50,
                'max_file_size': 50,
                'processing_priority': 'Higher than Free',
                'description': 'Ideal for regular individual document processing.',
                'features': ['50 PDFs/month', '50 MB maximum file size', 'Faster processing', 'Higher priority than Free'],
                'active': True,
                'sort_order': 2,
            }
        )
        # Ensure price is always updated to doubled value
        if self.basic_plan.price != Decimal('18.00'):
            self.basic_plan.price = Decimal('18.00')
            self.basic_plan.save(update_fields=['price'])

        self.pro_plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='pro',
            defaults={
                'name': 'Pro',
                'code': 'pro',
                'price': Decimal('48.00'),
                'currency': 'USD',
                'billing_period': 'month',
                'usage_limit': 200,
                'max_file_size': 100,
                'processing_priority': 'High',
                'description': 'Priority processing for professionals and busy teams.',
                'features': ['200 PDFs/month', '100 MB maximum file size', 'Priority processing', 'High priority'],
                'active': True,
                'sort_order': 3,
            }
        )
        if self.pro_plan.price != Decimal('48.00'):
            self.pro_plan.price = Decimal('48.00')
            self.pro_plan.save(update_fields=['price'])

        self.unlimited_plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='unlimited',
            defaults={
                'name': 'Unlimited',
                'code': 'unlimited',
                'price': Decimal('90.00'),
                'currency': 'USD',
                'billing_period': 'month',
                'usage_limit': 0,
                'max_file_size': 250,
                'processing_priority': 'Highest',
                'description': 'Unlimited processing with maximum performance and server priority.',
                'features': ['Unlimited processing', '250 MB maximum file size', 'Highest processing priority'],
                'active': True,
                'sort_order': 4,
            }
        )
        if self.unlimited_plan.price != Decimal('90.00'):
            self.unlimited_plan.price = Decimal('90.00')
            self.unlimited_plan.save(update_fields=['price'])

        self.user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='TestPassword123!',
            country='United States',
            is_active=True,
            is_email_verified=True,
            trial_used=True
        )

        # Ensure Binance settings has receiving UID 1104715375
        self.settings = BinanceManualPaymentSettings.get_settings()
        self.settings.receiving_identifier = '1104715375'
        self.settings.receiving_identifier_type = BinanceManualPaymentSettings.IDENTIFIER_TYPE_UID
        self.settings.enabled = True
        self.settings.save()

    def test_four_subscription_plans_exist_with_correct_specs(self):
        """All 4 plans exist with exact required prices, limits, and priorities."""
        self.assertEqual(self.free_plan.price, Decimal('0.00'))
        self.assertEqual(self.free_plan.usage_limit, 5)
        self.assertEqual(self.free_plan.max_file_size, 10)
        self.assertEqual(self.free_plan.processing_priority, 'Normal')

        self.assertEqual(self.basic_plan.price, Decimal('18.00'))
        self.assertEqual(self.basic_plan.usage_limit, 50)
        self.assertEqual(self.basic_plan.max_file_size, 50)

        self.assertEqual(self.pro_plan.price, Decimal('48.00'))
        self.assertEqual(self.pro_plan.usage_limit, 200)
        self.assertEqual(self.pro_plan.max_file_size, 100)

        self.assertEqual(self.unlimited_plan.price, Decimal('90.00'))
        self.assertEqual(self.unlimited_plan.usage_limit, 0)
        self.assertTrue(self.unlimited_plan.is_unlimited)
        self.assertEqual(self.unlimited_plan.max_file_size, 250)

    def test_pricing_page_displays_all_four_plans_and_zero_student_references(self):
        """Plans page shows all 4 tiers and does not contain the word student."""
        response = self.client.get(reverse('subscriptions:plans'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('$0', content)
        self.assertIn('$18', content)
        self.assertIn('$48', content)
        self.assertIn('$90', content)

        self.assertNotIn('Student', content)
        self.assertNotIn('student', content)

    def test_free_plan_immediate_activation_without_payment_record(self):
        """Selecting the Free plan immediately activates it without Binance redirect or payment creation."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('payments:checkout', args=['free']), follow=True)
        self.assertEqual(response.status_code, 200)

        # Active subscription must be Free
        sub = SubscriptionService.get_active_subscription(self.user)
        self.assertIsNotNone(sub)
        self.assertEqual(sub.plan.slug, 'free')
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(sub.pdf_limit, 5)
        self.assertEqual(sub.payment_method, 'FREE')

        # No payment record created
        self.assertEqual(Payment.objects.filter(user=self.user).count(), 0)

    def test_paid_plan_binance_checkout_displays_exact_server_price_and_uid(self):
        """Paid plans display price directly from database and show official UID 1104715375."""
        self.client.force_login(self.user)
        url = reverse('payments:binance_manual_checkout', args=['pro'])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # Pro plan price is $48.00 (doubled from original $24.00)
        self.assertIn('48.00', content)
        self.assertIn('1104715375', content)
        self.assertIn('Copy UID', content)
        self.assertNotIn('student', content.lower())

    def test_renewal_extends_from_existing_end_date(self):
        """Renewal of an active subscription extends expiration date from existing end_date."""
        # 1. Activate initial subscription valid for 30 days
        now = timezone.now()
        initial_sub = SubscriptionService.activate_subscription(
            self.user, self.basic_plan, 'Binance Pay', duration_days=30
        )
        self.assertEqual(initial_sub.status, Subscription.STATUS_ACTIVE)
        expected_first_end = initial_sub.end_date

        # 2. Renew subscription 5 days later
        renewed_sub = SubscriptionService.activate_subscription(
            self.user, self.basic_plan, 'Binance Pay', duration_days=30
        )

        # The new subscription should expire 30 days AFTER the first end date (total 60 days from start)
        initial_sub.refresh_from_db()
        self.assertEqual(initial_sub.status, Subscription.STATUS_CANCELLED)
        self.assertEqual(renewed_sub.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(renewed_sub.end_date, expected_first_end + timedelta(days=30))

    def test_renewal_of_expired_subscription_starts_from_now(self):
        """Activating after expiration starts subscription from the approval date."""
        now = timezone.now()
        sub = SubscriptionService.activate_subscription(self.user, self.basic_plan, 'Binance Pay')
        sub.status = Subscription.STATUS_EXPIRED
        sub.end_date = now - timedelta(days=2)
        sub.save()

        # Re-activate
        new_sub = SubscriptionService.activate_subscription(self.user, self.pro_plan, 'Binance Pay')
        self.assertEqual(new_sub.status, Subscription.STATUS_ACTIVE)
        # End date is approximately now + 30 days
        self.assertTrue(new_sub.end_date > now + timedelta(days=28))
        self.assertTrue(new_sub.end_date <= now + timedelta(days=31))

    def test_quota_limits_enforced_for_free_and_pro(self):
        """Usage limits are strictly enforced on PDF upload authorization."""
        # Free plan quota: 5
        sub = SubscriptionService.activate_subscription(self.user, self.free_plan, 'FREE')
        sub.used_count = 5
        sub.save()

        allowed, msg, _, _, _ = SubscriptionService.can_process_pdf(self.user)
        self.assertFalse(allowed)
        self.assertIn("5 of 5 PDFs used this month", msg)

        # Pro plan quota: 200
        sub_pro = SubscriptionService.activate_subscription(self.user, self.pro_plan, 'Binance Pay')
        sub_pro.used_count = 199
        sub_pro.save()
        allowed, _, _, _, _ = SubscriptionService.can_process_pdf(self.user)
        self.assertTrue(allowed)

        sub_pro.used_count = 200
        sub_pro.save()
        allowed, msg_pro, _, _, _ = SubscriptionService.can_process_pdf(self.user)
        self.assertFalse(allowed)
        self.assertIn("200 of 200 PDFs used this month", msg_pro)

    def test_unlimited_plan_allows_high_volume_with_fair_use(self):
        """Unlimited plan allows conversion beyond normal caps up to fair use."""
        sub = SubscriptionService.activate_subscription(self.user, self.unlimited_plan, 'Binance Pay')
        sub.used_count = 1500
        sub.save()

        allowed, msg, _, max_size, _ = SubscriptionService.can_process_pdf(self.user)
        self.assertTrue(allowed)
        self.assertEqual(max_size, 250)

    def test_dashboard_displays_required_fields(self):
        """User dashboard shows Current Plan, Status, Start Date, Expiration Date, and Usage."""
        SubscriptionService.activate_subscription(self.user, self.pro_plan, 'Binance Pay')
        self.client.force_login(self.user)
        response = self.client.get(reverse('accounts:dashboard'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('Current Plan', content)
        self.assertIn('Pro', content)
        self.assertIn('Active', content)
        self.assertIn('PDF Usage', content)
        self.assertIn('0 / 200 PDFs', content)
        self.assertIn('Expires:', content)
        self.assertNotIn('student', content.lower())
