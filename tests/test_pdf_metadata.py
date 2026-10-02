import os
import shutil
import tempfile
import subprocess
import pymupdf
import pypdf
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings

from pdf_processor.converter import PDFToImagePDFConverter
from pdf_processor.models import PDFProcessingJob
from pdf_processor.tasks import process_pdf_job_task
from subscriptions.models import SubscriptionPlan

User = get_user_model()


class MinimalPDFMetadataTests(TestCase):
    """
    Validation test suite for Humatron Minimal PDF Metadata specification:
    - Output PDF does NOT inherit or copy metadata from source PDF.
    - Output PDF contains only controlled minimal metadata (Producer: Humatron PDF Processor).
    - Forbidden metadata (author, subject, keywords, creator, dates, XMP, user info) is stripped.
    - Metadata inspected via PyMuPDF, pypdf, and exiftool.
    """

    @classmethod
    def setUpTestData(cls):
        # Create a sample PDF loaded with extensive source metadata and XMP packet
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 50), "Classified Financial Report - Highly Confidential", fontsize=14)
        doc.set_metadata({
            "author": "Dr. Sensitive Author",
            "title": "Confidential Strategic Blueprint",
            "subject": "Acquisition Financials",
            "keywords": "confidential, acquisition, financial, secrets",
            "creator": "Legacy Microsoft Office 2016",
            "producer": "Acrobat Distiller 11.0",
            "creationDate": "D:20180512143000Z",
            "modDate": "D:20200822184500Z",
        })
        xmp_payload = (
            "<x:xmpmeta xmlns:x='adobe:ns:meta/'>"
            "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>"
            "<rdf:Description rdf:about='' xmlns:dc='http://purl.org/dc/elements/1.1/'>"
            "<dc:description><rdf:Alt><rdf:li xml:lang='x-default'>"
            "Sensitive Corporate Internal Secrets"
            "</rdf:li></rdf:Alt></dc:description>"
            "</rdf:Description></rdf:RDF></x:xmpmeta>"
        )
        if hasattr(doc, "set_xml_metadata"):
            doc.set_xml_metadata(xmp_payload)

        cls.heavy_pdf_bytes = doc.tobytes()
        doc.close()

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="humatron_meta_test_")
        self.input_pdf_path = os.path.join(self.temp_dir, "source_input.pdf")
        self.output_pdf_path = os.path.join(self.temp_dir, "processed_output.pdf")
        with open(self.input_pdf_path, "wb") as f:
            f.write(self.heavy_pdf_bytes)

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_source_metadata_is_not_inherited_in_output(self):
        """
        Verify that original author, title, subject, keywords, creator, producer,
        and dates are completely stripped and NOT copied into the output PDF.
        """
        result = PDFToImagePDFConverter.convert(self.input_pdf_path, self.output_pdf_path)
        self.assertTrue(os.path.exists(self.output_pdf_path))
        self.assertGreater(result['output_size_bytes'], 0)

        # 1. Inspect with PyMuPDF
        out_doc = pymupdf.open(self.output_pdf_path)
        meta = out_doc.metadata

        # Assert preferred metadata is present
        self.assertEqual(meta.get('producer'), 'Humatron PDF Processor')

        # Assert original metadata is NOT preserved
        self.assertNotEqual(meta.get('author'), 'Dr. Sensitive Author')
        self.assertEqual(meta.get('author'), '')
        self.assertNotEqual(meta.get('title'), 'Confidential Strategic Blueprint')
        self.assertEqual(meta.get('title'), '')
        self.assertNotEqual(meta.get('subject'), 'Acquisition Financials')
        self.assertEqual(meta.get('subject'), '')
        self.assertNotEqual(meta.get('keywords'), 'confidential, acquisition, financial, secrets')
        self.assertEqual(meta.get('keywords'), '')
        self.assertNotEqual(meta.get('creator'), 'Legacy Microsoft Office 2016')
        self.assertEqual(meta.get('creator'), '')
        self.assertNotEqual(meta.get('creationDate'), 'D:20180512143000Z')
        self.assertEqual(meta.get('creationDate'), '')
        self.assertNotEqual(meta.get('modDate'), 'D:20200822184500Z')
        self.assertEqual(meta.get('modDate'), '')

        # Assert XMP metadata is stripped
        xml_meta = out_doc.get_xml_metadata()
        self.assertEqual(xml_meta, '')
        out_doc.close()

        # 2. Inspect with pypdf
        reader = pypdf.PdfReader(self.output_pdf_path)
        pypdf_meta = reader.metadata or {}
        self.assertEqual(pypdf_meta.get('/Producer'), 'Humatron PDF Processor')
        self.assertIsNone(pypdf_meta.get('/Author'))
        self.assertIsNone(pypdf_meta.get('/Subject'))
        self.assertIsNone(pypdf_meta.get('/Keywords'))
        self.assertIsNone(pypdf_meta.get('/Creator'))
        self.assertIsNone(pypdf_meta.get('/CreationDate'))
        self.assertIsNone(pypdf_meta.get('/ModDate'))
        self.assertIsNone(reader.xmp_metadata)

    def test_exiftool_inspection_confirms_minimal_metadata(self):
        """
        Verify metadata using external exiftool:
        exiftool -a -u -g1 output.pdf
        """
        PDFToImagePDFConverter.convert(self.input_pdf_path, self.output_pdf_path)

        exiftool_proc = subprocess.run(
            ["exiftool", "-a", "-u", "-g1", self.output_pdf_path],
            capture_output=True,
            text=True
        )
        self.assertEqual(exiftool_proc.returncode, 0)
        output = exiftool_proc.stdout

        # Verify Humatron Producer is present
        self.assertIn("Humatron PDF Processor", output)

        # Verify sensitive and original metadata are absent from exiftool output
        self.assertNotIn("Dr. Sensitive Author", output)
        self.assertNotIn("Confidential Strategic Blueprint", output)
        self.assertNotIn("Acquisition Financials", output)
        self.assertNotIn("Legacy Microsoft Office", output)
        self.assertNotIn("Acrobat Distiller", output)
        self.assertNotIn("Sensitive Corporate Internal Secrets", output)
        self.assertNotIn("2018:05:12", output)
        self.assertNotIn("2020:08:22", output)

    def test_user_identifying_information_is_strictly_excluded(self):
        """
        Verify that user-identifying info (email, username, account ID, filename,
        IP, timestamps, server hostname) cannot be injected into the PDF metadata.
        """
        malicious_or_leak_metadata = {
            'producer': 'Humatron PDF Processor',
            'user_email': 'victim@domain.com',
            'user_name': 'Secret User',
            'account_id': 'ACC-99999',
            'original_filename': 'my_passport_scan.pdf',
            'ip_address': '192.168.1.100',
            'upload_timestamp': '2026-09-27T12:00:00Z',
            'internal_path': '/var/www/humatron/secret.pdf',
            'server_hostname': 'node-1.prod.humatron.me',
            'job_id': 'job-abc-123',
            'author': 'Malicious Injection',
            'subject': 'Malicious Subject',
        }

        PDFToImagePDFConverter.convert(
            self.input_pdf_path,
            self.output_pdf_path,
            metadata=malicious_or_leak_metadata
        )

        out_doc = pymupdf.open(self.output_pdf_path)
        meta = out_doc.metadata
        self.assertEqual(meta.get('author'), '')
        self.assertEqual(meta.get('subject'), '')
        self.assertEqual(meta.get('producer'), 'Humatron PDF Processor')
        out_doc.close()

        # Check raw file bytes for any leaked keys/values
        with open(self.output_pdf_path, 'rb') as f:
            raw_pdf_bytes = f.read()

        for forbidden_string in [
            b'victim@domain.com',
            b'Secret User',
            b'ACC-99999',
            b'my_passport_scan.pdf',
            b'192.168.1.100',
            b'node-1.prod.humatron.me',
            b'job-abc-123',
            b'Malicious Injection',
        ]:
            self.assertNotIn(forbidden_string, raw_pdf_bytes)

    @override_settings(
        PDF_METADATA_PRODUCER="Humatron PDF Processor",
        PDF_METADATA_TITLE="Humatron Processed PDF",
        PDF_METADATA_CREATOR="Humatron"
    )
    def test_optional_controlled_title_and_creator_metadata(self):
        """
        Verify that controlled Title and Creator can be applied when configured,
        without leaking any source document metadata.
        """
        PDFToImagePDFConverter.convert(self.input_pdf_path, self.output_pdf_path)

        reader = pypdf.PdfReader(self.output_pdf_path)
        meta = reader.metadata or {}
        self.assertEqual(meta.get('/Producer'), 'Humatron PDF Processor')
        self.assertEqual(meta.get('/Title'), 'Humatron Processed PDF')
        self.assertEqual(meta.get('/Creator'), 'Humatron')
        self.assertIsNone(meta.get('/Author'))
        self.assertIsNone(meta.get('/Subject'))
        self.assertIsNone(meta.get('/Keywords'))

        # Also inspect via exiftool
        proc = subprocess.run(
            ["exiftool", "-a", "-u", "-g1", self.output_pdf_path],
            capture_output=True,
            text=True
        )
        self.assertIn("Humatron PDF Processor", proc.stdout)
        self.assertIn("Humatron Processed PDF", proc.stdout)
        self.assertIn("Humatron", proc.stdout)
        self.assertNotIn("Dr. Sensitive Author", proc.stdout)

    def test_background_celery_task_produces_sanitized_metadata(self):
        """
        End-to-end integration test:
        PDFProcessingJob processed by background Celery worker task produces
        output with sanitized minimal metadata.
        """
        user = User.objects.create_user(
            username='task_meta_user@humatron.me',
            email='task_meta_user@humatron.me',
            password='StrongPassword123!',
            is_active=True,
            is_email_verified=True
        )
        plan = SubscriptionPlan.objects.create(
            name='Test Plan',
            code='test-meta-plan',
            price=20.00,
            price_etb=2700.00,
            duration_days=30,
            pdf_limit=10,
            max_file_size_mb=10,
            max_pages_per_pdf=50
        )
        from subscriptions.services import SubscriptionService
        SubscriptionService.activate_subscription(user, plan, 'Binance Pay')

        # Place input in media/uploads
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        stored_filename = "test_meta_upload.pdf"
        input_target = os.path.join(upload_dir, stored_filename)
        with open(input_target, "wb") as f:
            f.write(self.heavy_pdf_bytes)

        job = PDFProcessingJob.objects.create(
            user=user,
            original_filename="confidential_secrets.pdf",
            stored_filename=stored_filename,
            page_count=1,
            input_size=len(self.heavy_pdf_bytes),
            status=PDFProcessingJob.STATUS_QUEUED
        )

        try:
            # Run background task synchronously
            process_pdf_job_task(str(job.id))

            job.refresh_from_db()
            self.assertEqual(job.status, PDFProcessingJob.STATUS_COMPLETED)
            self.assertTrue(job.processed_filename)

            output_file_path = os.path.join(settings.MEDIA_ROOT, 'processed', job.processed_filename)
            self.assertTrue(os.path.exists(output_file_path))

            # Verify sanitized metadata on generated file
            out_doc = pymupdf.open(output_file_path)
            self.assertEqual(out_doc.metadata.get('producer'), 'Humatron PDF Processor')
            self.assertEqual(out_doc.metadata.get('author'), '')
            self.assertEqual(out_doc.metadata.get('title'), '')
            self.assertEqual(out_doc.metadata.get('subject'), '')
            self.assertEqual(out_doc.get_xml_metadata(), '')
            out_doc.close()

            # Ensure original filename was not embedded in metadata
            with open(output_file_path, "rb") as f:
                content = f.read()
            self.assertNotIn(b"confidential_secrets.pdf", content)
            self.assertNotIn(b"Dr. Sensitive Author", content)

        finally:
            if os.path.exists(input_target):
                os.remove(input_target)
            if job.processed_filename:
                out_path = os.path.join(settings.MEDIA_ROOT, 'processed', job.processed_filename)
                if os.path.exists(out_path):
                    os.remove(out_path)
