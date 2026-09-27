from django.test import TestCase
from django.contrib.auth import get_user_model
from subscriptions.models import SubscriptionPlan, Subscription
from subscriptions.services import SubscriptionService
from pdf_processor.models import PDFProcessingJob
from usage.models import UsageRecord
from usage.services import UsageService

User = get_user_model()


class TrialAndUsageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='trial_user@humatron.me',
            email='trial_user@humatron.me',
            password='StrongPassword123!',
            is_active=True,
            is_email_verified=True,
            trial_used=False
        )
        self.plan = SubscriptionPlan.objects.create(
            name='Starter',
            code='starter',
            price=20.00,
            price_etb=2700.00,
            duration_days=30,
            pdf_limit=10,
            max_file_size_mb=25,
            max_pages_per_pdf=100
        )

    def test_trial_available_for_new_verified_user(self):
        self.assertTrue(SubscriptionService.is_trial_available(self.user))
        allowed, msg, is_trial, max_size, max_pages = SubscriptionService.can_process_pdf(self.user)
        self.assertTrue(allowed)
        self.assertTrue(is_trial)

    def test_trial_consumed_after_first_job(self):
        # Create a completed job for user under trial
        job1 = PDFProcessingJob.objects.create(
            user=self.user,
            original_filename='trial1.pdf',
            stored_filename='trial1.pdf',
            status=PDFProcessingJob.STATUS_COMPLETED
        )

        record1 = UsageService.record_job_usage(job1)
        self.assertEqual(record1.usage_type, UsageRecord.TYPE_TRIAL)
        self.assertEqual(record1.quantity, 1)

        self.user.refresh_from_db()
        self.assertTrue(self.user.trial_used)
        self.assertFalse(SubscriptionService.is_trial_available(self.user))

        # Second attempt without subscription is rejected
        allowed, msg, is_trial, _, _ = SubscriptionService.can_process_pdf(self.user)
        self.assertFalse(allowed)
        self.assertIn("Please subscribe to continue", msg)

    def test_idempotent_usage_deduction(self):
        # Active subscription
        sub = SubscriptionService.activate_subscription(self.user, self.plan, 'Test')
        self.assertEqual(sub.used_count, 0)

        job = PDFProcessingJob.objects.create(
            user=self.user,
            original_filename='sub_doc.pdf',
            stored_filename='sub_doc.pdf',
            status=PDFProcessingJob.STATUS_COMPLETED
        )

        # First deduction
        rec1 = UsageService.record_job_usage(job)
        sub.refresh_from_db()
        self.assertEqual(sub.used_count, 1)
        self.assertEqual(UsageRecord.objects.filter(processing_job=job).count(), 1)

        # Simulated Celery worker retry of the same job (Section 25)
        rec2 = UsageService.record_job_usage(job)
        sub.refresh_from_db()
        self.assertEqual(sub.used_count, 1, "Retried job must not deduct usage twice!")
        self.assertEqual(rec1.id, rec2.id)
        self.assertEqual(UsageRecord.objects.filter(processing_job=job).count(), 1)
