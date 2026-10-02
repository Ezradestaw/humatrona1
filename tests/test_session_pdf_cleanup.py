import os
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from subscriptions.models import SubscriptionPlan
from subscriptions.services import SubscriptionService
from pdf_processor.models import PDFProcessingJob

User = get_user_model()


class SessionPDFCleanupTests(TestCase):
    """
    Test that after a PDF is processed, when that session ends (e.g. logout),
    the PDF files (both input and processed) are completely removed from disk.
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='session_user@humatron.me',
            email='session_user@humatron.me',
            password='Password123!',
            is_active=True,
            is_email_verified=True,
            country='United States'
        )

        # Plan with unlimited/sufficient quota
        self.plan, _ = SubscriptionPlan.objects.update_or_create(
            slug='basic',
            defaults={
                'name': 'Basic',
                'price': Decimal('9.00'),
                'usage_limit': 50,
                'max_file_size': 50,
                'active': True
            }
        )
        SubscriptionService.activate_subscription(self.user, self.plan, payment_method='TEST')

        os.makedirs(os.path.join(settings.MEDIA_ROOT, 'uploads'), exist_ok=True)
        os.makedirs(os.path.join(settings.MEDIA_ROOT, 'processed'), exist_ok=True)

    def test_pdf_removed_after_session_ends(self):
        self.client.force_login(self.user)

        # Create dummy upload and processed files
        dummy_input = "test_input_session.pdf"
        dummy_output = "test_output_session.pdf"

        input_path = os.path.join(settings.MEDIA_ROOT, 'uploads', dummy_input)
        output_path = os.path.join(settings.MEDIA_ROOT, 'processed', dummy_output)

        with open(input_path, 'wb') as f:
            f.write(b"%PDF-1.4 dummy input content")
        with open(output_path, 'wb') as f:
            f.write(b"%PDF-1.4 dummy output content")

        self.assertTrue(os.path.exists(input_path))
        self.assertTrue(os.path.exists(output_path))

        # Get session
        session = self.client.session
        session_key = session.session_key or 'test_session_123'

        job = PDFProcessingJob.objects.create(
            user=self.user,
            original_filename="sample.pdf",
            stored_filename=dummy_input,
            processed_filename=dummy_output,
            status=PDFProcessingJob.STATUS_COMPLETED,
            session_key=session_key,
        )

        session['pdf_job_ids'] = [str(job.id)]
        session.save()

        # Logout ends the session
        response = self.client.get(reverse('accounts:logout'))
        self.assertEqual(response.status_code, 302)

        # Files must be removed from disk
        self.assertFalse(os.path.exists(input_path))
        self.assertFalse(os.path.exists(output_path))

        job.refresh_from_db()
        self.assertTrue(job.is_files_deleted)
        self.assertEqual(job.status, PDFProcessingJob.STATUS_EXPIRED)
