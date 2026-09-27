import os
import io
import pymupdf
from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.urls import reverse

from pdf_processor.converter import PDFToImagePDFConverter
from pdf_processor.validators import validate_pdf_file, sanitize_filename
from pdf_processor.models import PDFProcessingJob
from subscriptions.models import SubscriptionPlan, Subscription

User = get_user_model()


class PDFProcessingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Create a sample valid multi-page PDF in memory using pymupdf
        doc = pymupdf.open()
        page1 = doc.new_page(width=595, height=842) # A4
        page1.insert_text((50, 50), "Humatron Confidential Sample Page 1", fontsize=16)
        page2 = doc.new_page(width=595, height=842)
        page2.insert_text((50, 50), "Humatron Confidential Sample Page 2", fontsize=16)
        cls.valid_pdf_bytes = doc.tobytes()
        doc.close()

    def setUp(self):
        self.user1 = User.objects.create_user(
            username='user1@humatron.me',
            email='user1@humatron.me',
            password='StrongPassword123!',
            is_active=True,
            is_email_verified=True
        )
        self.user2 = User.objects.create_user(
            username='user2@humatron.me',
            email='user2@humatron.me',
            password='StrongPassword123!',
            is_active=True,
            is_email_verified=True
        )
        self.plan = SubscriptionPlan.objects.create(
            name='Test Professional',
            code='test-pro',
            price=50.00,
            price_etb=6750.00,
            duration_days=30,
            pdf_limit=25,
            max_file_size_mb=50,
            max_pages_per_pdf=200
        )

    def test_sanitize_filename_prevents_path_traversal(self):
        malicious_name = "../../../etc/passwd"
        sanitized = sanitize_filename(malicious_name)
        self.assertNotIn('/', sanitized)
        self.assertNotIn('..', sanitized)
        self.assertTrue(sanitized.endswith('.pdf'))

    def test_validate_pdf_accepts_valid_pdf(self):
        upload = SimpleUploadedFile("valid.pdf", self.valid_pdf_bytes, content_type="application/pdf")
        metadata = validate_pdf_file(upload)
        self.assertEqual(metadata['page_count'], 2)
        self.assertGreater(metadata['file_size'], 0)

    def test_validate_pdf_rejects_non_pdf_content(self):
        upload = SimpleUploadedFile("fake.pdf", b"<html><body>Not a real PDF</body></html>", content_type="application/pdf")
        with self.assertRaises(ValidationError):
            validate_pdf_file(upload)

    def test_converter_converts_pages_to_image_pdf(self):
        # Setup paths
        input_path = "/tmp/humatron_test_input.pdf"
        output_path = "/tmp/humatron_test_output.pdf"

        try:
            with open(input_path, 'wb') as f:
                f.write(self.valid_pdf_bytes)

            result = PDFToImagePDFConverter.convert(input_path, output_path)
            self.assertEqual(result['page_count'], 2)
            self.assertTrue(os.path.exists(output_path))
            self.assertGreater(result['output_size_bytes'], 0)

            # Inspect output PDF
            out_doc = pymupdf.open(output_path)
            self.assertEqual(len(out_doc), 2)
            
            # Verify original dimensions are preserved
            self.assertEqual(round(out_doc[0].rect.width), 595)
            self.assertEqual(round(out_doc[0].rect.height), 842)

            # Verify that text layer has been flattened into images
            extracted_text = out_doc[0].get_text()
            self.assertEqual(extracted_text.strip(), "", "Flattened PDF must not contain selectable text.")

            # Verify page contains image
            images = out_doc[0].get_images()
            self.assertGreaterEqual(len(images), 1, "Page must contain the rendered raster image.")
            out_doc.close()

        finally:
            if os.path.exists(input_path):
                os.remove(input_path)
            if os.path.exists(output_path):
                os.remove(output_path)

    def test_download_authorization_and_idor_prevention(self):
        # Create a job owned by user1
        job = PDFProcessingJob.objects.create(
            user=self.user1,
            original_filename='user1_doc.pdf',
            stored_filename='user1_stored.pdf',
            processed_filename='user1_processed.pdf',
            page_count=2,
            input_size=1000,
            output_size=2000,
            status=PDFProcessingJob.STATUS_COMPLETED
        )

        # Place a dummy file in processed dir
        from django.conf import settings
        proc_dir = os.path.join(settings.MEDIA_ROOT, 'processed')
        os.makedirs(proc_dir, exist_ok=True)
        file_path = os.path.join(proc_dir, 'user1_processed.pdf')
        with open(file_path, 'wb') as f:
            f.write(self.valid_pdf_bytes)

        download_url = reverse('pdf_processor:download', kwargs={'job_id': job.id})

        # 1. Unauthenticated user gets redirected to login
        anon_client = Client()
        anon_resp = anon_client.get(download_url)
        self.assertEqual(anon_resp.status_code, 302)

        # 2. User2 (other user) attempts to access User1's job -> 404 (IDOR prevented)
        client2 = Client()
        client2.force_login(self.user2)
        resp2 = client2.get(download_url)
        self.assertEqual(resp2.status_code, 404)

        # 3. User1 (owner) can download successfully
        client1 = Client()
        client1.force_login(self.user1)
        resp1 = client1.get(download_url)
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1['Content-Type'], 'application/pdf')
        self.assertIn('attachment;', resp1['Content-Disposition'])

        # Verify download count incremented
        job.refresh_from_db()
        self.assertEqual(job.download_count, 1)

        # Cleanup
        if os.path.exists(file_path):
            os.remove(file_path)
