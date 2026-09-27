import io
from datetime import timedelta
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes

from accounts.models import ApprovedEducationalDomain, StudentVerification
from accounts.forms import StudentVerificationForm
from accounts.tokens import educational_email_token
from subscriptions.models import SubscriptionPlan, Subscription
from subscriptions.services import PricingCalculator
from payments.models import Payment
from payments.services import PaymentService

User = get_user_model()


class StudentVerificationTests(TestCase):
    """
    Comprehensive tests for the 25% Student Discount & Verification Workflow (Sections 7-19).
    """

    def setUp(self):
        self.client = Client()

        # Approved educational domains
        ApprovedEducationalDomain.objects.create(
            domain='edu',
            institution_name='Educational Institutions Worldwide',
            is_active=True
        )
        ApprovedEducationalDomain.objects.create(
            domain='aau.edu.et',
            institution_name='Addis Ababa University',
            is_active=True
        )

        self.plan = SubscriptionPlan.objects.create(
            code='professional',
            name='Professional',
            price=Decimal('50.00'),
            price_etb=Decimal('6750.00'),
            currency='USD',
            duration_days=30,
            pdf_limit=200,
            max_file_size_mb=50,
            max_pages_per_pdf=200,
            active=True
        )

        self.student_user = User.objects.create_user(
            username='student@aau.edu.et',
            email='student@aau.edu.et',
            password='Password123!',
            first_name='Abebe',
            last_name='Tadesse',
            country='Ethiopia',
            job_title='Student',
            is_active=True,
            is_email_verified=True
        )

        self.other_user = User.objects.create_user(
            username='other@humatron.me',
            email='other@humatron.me',
            password='Password123!',
            country='Ethiopia',
            is_active=True,
            is_email_verified=True
        )

        self.staff_user = User.objects.create_user(
            username='staff@humatron.me',
            email='staff@humatron.me',
            password='Password123!',
            is_staff=True,
            is_active=True,
            is_email_verified=True
        )

    def test_job_title_student_does_not_grant_discount(self):
        """Selecting Job title = Student alone does NOT grant student discount."""
        self.assertEqual(self.student_user.job_title, 'Student')
        self.assertFalse(self.student_user.is_verified_student)

        pricing = PricingCalculator.calculate(self.plan, self.student_user)
        self.assertFalse(pricing['is_student_discount'])
        self.assertEqual(pricing['final_usd'], Decimal('50.00'))
        self.assertEqual(pricing['final_etb'], Decimal('6750.00'))

    def test_approved_educational_domain_matching(self):
        """Domain matching supports exact domains and domain suffixes."""
        self.assertTrue(ApprovedEducationalDomain.is_domain_approved('john@mit.edu'))
        self.assertTrue(ApprovedEducationalDomain.is_domain_approved('abebe@aau.edu.et'))
        self.assertTrue(ApprovedEducationalDomain.is_domain_approved('cs.student@dept.aau.edu.et'))
        self.assertFalse(ApprovedEducationalDomain.is_domain_approved('spammer@gmail.com'))
        self.assertFalse(ApprovedEducationalDomain.is_domain_approved('fraud@yahoo.com'))

    def test_form_validation_rejects_expired_id(self):
        """Student verification form rejects expired student ID dates."""
        yesterday = timezone.now().date() - timedelta(days=1)
        pdf_file = SimpleUploadedFile("id.pdf", b"%PDF-1.4 test content", content_type="application/pdf")

        form = StudentVerificationForm(data={
            'educational_email': 'student@aau.edu.et',
            'educational_institution': 'Addis Ababa University',
            'student_id_expiration_date': yesterday,
        }, files={'student_id_file': pdf_file})

        self.assertFalse(form.is_valid())
        self.assertIn('student_id_expiration_date', form.errors)
        self.assertIn('expired', form.errors['student_id_expiration_date'][0].lower())

    def test_form_validation_rejects_non_approved_domain(self):
        """Student verification form rejects non-educational email domains."""
        future_date = timezone.now().date() + timedelta(days=180)
        pdf_file = SimpleUploadedFile("id.pdf", b"%PDF-1.4 test content", content_type="application/pdf")

        form = StudentVerificationForm(data={
            'educational_email': 'student@gmail.com',
            'educational_institution': 'Some University',
            'student_id_expiration_date': future_date,
        }, files={'student_id_file': pdf_file})

        self.assertFalse(form.is_valid())
        self.assertIn('educational_email', form.errors)
        self.assertIn('not currently in the approved', form.errors['educational_email'][0])

    def test_form_validation_rejects_unsupported_file_type(self):
        """Student verification form rejects executable or unsupported file types."""
        future_date = timezone.now().date() + timedelta(days=180)
        exe_file = SimpleUploadedFile("malware.exe", b"MZ fake executable", content_type="application/x-msdownload")

        form = StudentVerificationForm(data={
            'educational_email': 'student@aau.edu.et',
            'educational_institution': 'Addis Ababa University',
            'student_id_expiration_date': future_date,
        }, files={'student_id_file': exe_file})

        self.assertFalse(form.is_valid())
        self.assertIn('student_id_file', form.errors)

    def test_educational_email_token_verification(self):
        """Single-use cryptographic token verifies educational email address."""
        verification = StudentVerification.objects.create(
            user=self.student_user,
            educational_email='student@aau.edu.et',
            educational_institution='Addis Ababa University',
            educational_email_verified=False,
            status=StudentVerification.STATUS_PENDING
        )

        uidb64 = urlsafe_base64_encode(force_bytes(self.student_user.pk))
        token = educational_email_token.make_token(self.student_user)

        self.client.force_login(self.student_user)
        verify_url = reverse('accounts:verify_educational_email', kwargs={'uidb64': uidb64, 'token': token})
        response = self.client.get(verify_url, follow=True)
        self.assertEqual(response.status_code, 200)

        verification.refresh_from_db()
        self.assertTrue(verification.educational_email_verified)

        # Token cannot be re-used
        self.assertFalse(educational_email_token.check_token(self.student_user, token))

    def test_admin_approval_grants_25_percent_discount(self):
        """Admin approval activates 25% discount and updates status to VERIFIED."""
        future_date = timezone.now().date() + timedelta(days=365)
        pdf_file = SimpleUploadedFile("studentid.pdf", b"%PDF-1.4 ID content", content_type="application/pdf")

        verification = StudentVerification.objects.create(
            user=self.student_user,
            educational_email='student@aau.edu.et',
            educational_institution='Addis Ababa University',
            educational_email_verified=True,
            student_id_file=pdf_file,
            student_id_expiration_date=future_date,
            status=StudentVerification.STATUS_UNDER_REVIEW,
            submitted_at=timezone.now()
        )

        self.assertFalse(self.student_user.is_verified_student)

        # Admin approves
        verification.status = StudentVerification.STATUS_VERIFIED
        verification.verified_at = timezone.now()
        verification.reviewed_by = self.staff_user
        verification.reviewed_at = timezone.now()
        verification.save()

        self.student_user.refresh_from_db()
        self.assertTrue(self.student_user.is_verified_student)

        # Price calculation with 25% discount
        pricing = PricingCalculator.calculate(self.plan, self.student_user)
        self.assertTrue(pricing['is_student_discount'])
        self.assertEqual(pricing['discount_percentage'], Decimal('25.00'))
        # USD: 50.00 * 0.75 = 37.50
        self.assertEqual(pricing['original_usd'], Decimal('50.00'))
        self.assertEqual(pricing['discount_usd'], Decimal('12.50'))
        self.assertEqual(pricing['final_usd'], Decimal('37.50'))
        # ETB: 6750.00 * 0.75 = 5062.50
        self.assertEqual(pricing['original_etb'], Decimal('6750.00'))
        self.assertEqual(pricing['discount_etb'], Decimal('1687.50'))
        self.assertEqual(pricing['final_etb'], Decimal('5062.50'))

    def test_admin_rejection_records_reason(self):
        """Admin rejection records reason and keeps student discount inactive."""
        verification = StudentVerification.objects.create(
            user=self.student_user,
            educational_email='student@aau.edu.et',
            educational_institution='Addis Ababa University',
            status=StudentVerification.STATUS_UNDER_REVIEW
        )

        verification.status = StudentVerification.STATUS_REJECTED
        verification.rejected_at = timezone.now()
        verification.rejection_reason = "Expired student card attached."
        verification.reviewed_by = self.staff_user
        verification.reviewed_at = timezone.now()
        verification.save()

        self.student_user.refresh_from_db()
        self.assertFalse(self.student_user.is_verified_student)

    def test_expired_student_id_automatically_revokes_discount(self):
        """When student ID expiration date is passed, discount is revoked and status is EXPIRED."""
        yesterday = timezone.now().date() - timedelta(days=1)
        verification = StudentVerification.objects.create(
            user=self.student_user,
            educational_email='student@aau.edu.et',
            educational_institution='Addis Ababa University',
            educational_email_verified=True,
            student_id_expiration_date=yesterday,
            status=StudentVerification.STATUS_VERIFIED
        )

        self.assertFalse(verification.is_active_and_verified)
        verification.refresh_from_db()
        self.assertEqual(verification.status, StudentVerification.STATUS_EXPIRED)
        self.assertFalse(self.student_user.is_verified_student)

    def test_telebirr_payment_records_discount_audit_trail(self):
        """Telebirr payment records 25% discount and audit fields on Payment and Subscription."""
        future_date = timezone.now().date() + timedelta(days=365)
        StudentVerification.objects.create(
            user=self.student_user,
            educational_email='student@aau.edu.et',
            educational_institution='Addis Ababa University',
            educational_email_verified=True,
            student_id_expiration_date=future_date,
            status=StudentVerification.STATUS_VERIFIED
        )
        self.assertTrue(self.student_user.is_verified_student)

        # Expected amount is 5062.50 ETB (25% off 6750.00 ETB)
        raw_msg = (
            "You have transferred 5062.50 ETB to Humatron Technologies (0911000000). "
            "Transaction number TX_STUDENT_DISCOUNT_01 on 2026-09-27."
        )
        success, msg, payment = PaymentService.verify_and_activate_telebirr(
            user=self.student_user,
            plan=self.plan,
            raw_message=raw_msg
        )
        self.assertTrue(success, msg)
        self.assertIsNotNone(payment)

        # Audit checks on Payment
        self.assertTrue(payment.student_discount_applied)
        self.assertEqual(payment.discount_percentage, Decimal('25.00'))
        self.assertEqual(payment.original_amount, Decimal('6750.00'))
        self.assertEqual(payment.discount_amount, Decimal('1687.50'))
        self.assertEqual(payment.final_amount, Decimal('5062.50'))
        self.assertEqual(payment.payment_country, 'Ethiopia')

        # Audit checks on Subscription
        sub = payment.subscription
        self.assertIsNotNone(sub)
        self.assertTrue(sub.student_discount_applied)
        self.assertEqual(sub.discount_percentage, Decimal('25.00'))
        self.assertEqual(sub.payment_country, 'Ethiopia')

    def test_private_document_access_control(self):
        """Student ID file is only accessible by the owner and staff members."""
        pdf_file = SimpleUploadedFile("private_id.pdf", b"%PDF-1.4 private student id", content_type="application/pdf")
        verification = StudentVerification.objects.create(
            user=self.student_user,
            educational_email='student@aau.edu.et',
            student_id_file=pdf_file,
            status=StudentVerification.STATUS_UNDER_REVIEW
        )

        doc_url = reverse('accounts:student_id_document', args=[verification.id])

        # 1. Other non-staff user is forbidden (403)
        self.client.force_login(self.other_user)
        response = self.client.get(doc_url)
        self.assertEqual(response.status_code, 403)

        # 2. Owner can access (200)
        self.client.force_login(self.student_user)
        response = self.client.get(doc_url)
        self.assertEqual(response.status_code, 200)

        # 3. Staff can access (200)
        self.client.force_login(self.staff_user)
        response = self.client.get(doc_url)
        self.assertEqual(response.status_code, 200)
