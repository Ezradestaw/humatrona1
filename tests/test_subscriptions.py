from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from subscriptions.models import SubscriptionPlan, Subscription
from subscriptions.services import SubscriptionService

User = get_user_model()


class SubscriptionLifecycleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='subscriber@humatron.me',
            email='subscriber@humatron.me',
            password='StrongPassword123!',
            is_active=True,
            is_email_verified=True,
            trial_used=True  # Trial already spent
        )
        self.plan = SubscriptionPlan.objects.create(
            name='Professional',
            code='professional',
            price=50.00,
            price_etb=6750.00,
            duration_days=30,
            pdf_limit=25,
            max_file_size_mb=50,
            max_pages_per_pdf=200,
            active=True
        )

    def test_active_subscription_grants_processing_permission(self):
        sub = SubscriptionService.activate_subscription(self.user, self.plan, 'PayPal')
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)
        self.assertTrue(sub.is_valid)

        allowed, msg, is_trial, max_size, max_pages = SubscriptionService.can_process_pdf(self.user)
        self.assertTrue(allowed)
        self.assertFalse(is_trial)
        self.assertEqual(max_size, 50)
        self.assertEqual(max_pages, 200)

    def test_expired_subscription_blocks_processing(self):
        sub = SubscriptionService.activate_subscription(self.user, self.plan, 'PayPal')
        # Manually backdate end_date to simulate expiration
        sub.end_date = timezone.now() - timedelta(days=1)
        sub.save(update_fields=['end_date'])

        # Service must automatically detect lapsed date and mark EXPIRED
        active_sub = SubscriptionService.get_active_subscription(self.user)
        self.assertIsNone(active_sub)

        allowed, msg, _, _, _ = SubscriptionService.can_process_pdf(self.user)
        self.assertFalse(allowed)

    def test_quota_limit_enforced(self):
        sub = SubscriptionService.activate_subscription(self.user, self.plan, 'PayPal')
        sub.used_count = 25  # Reached full limit
        sub.save(update_fields=['used_count'])

        allowed, msg, _, _, _ = SubscriptionService.can_process_pdf(self.user)
        self.assertFalse(allowed)
        self.assertIn("limit of 25 PDFs", msg)

    def test_subscription_renewal(self):
        sub1 = SubscriptionService.activate_subscription(self.user, self.plan, 'PayPal')
        self.assertEqual(sub1.status, Subscription.STATUS_ACTIVE)

        # Renew
        sub2 = SubscriptionService.activate_subscription(self.user, self.plan, 'PayPal')
        sub1.refresh_from_db()
        self.assertEqual(sub1.status, Subscription.STATUS_CANCELLED)
        self.assertEqual(sub2.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(sub2.used_count, 0)
