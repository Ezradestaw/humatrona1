from decimal import Decimal
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.core import mail
from django.contrib.auth import get_user_model
from django.conf import settings

from notifications.services import EmailService, sanitize_email_error, get_email_connection
from notifications.models import Notification
from subscriptions.models import SubscriptionPlan, Subscription
from payments.models import Payment
from pdf_processor.models import PDFProcessingJob
from contact.models import ContactMessage

User = get_user_model()


class SMTPEmailRoutingAndSecurityTests(TestCase):
    """
    Tests for Sections 1-19 of the Humatron Specification Modifications:
    - Dedicated sender routing: support@humatron.me vs. contact@humatron.me vs. admin@humatron.me
    - Registration email verification
    - Secure password-reset emails (no account leakage)
    - User notifications (Payments, Subscriptions, Student, PDF)
    - Contact form flow (admin notification, Reply-To header, safe sender)
    - Secret sanitization (never log or expose App Passwords)
    - Administrator SMTP test tool
    """

    def setUp(self):
        self.client = Client()
        mail.outbox = []

        self.user = User.objects.create_user(
            username='user@humatron.me',
            email='user@humatron.me',
            password='TestPassword123!',
            first_name='Abebe',
            last_name='Kebede',
            country='Ethiopia',
            is_active=True,
            is_email_verified=True
        )

        self.admin_user = User.objects.create_user(
            username='admin@humatron.me',
            email='admin@humatron.me',
            password='AdminPassword123!',
            is_staff=True,
            is_superuser=True,
            is_active=True,
            is_email_verified=True
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

    def test_registration_verification_email_sent_from_support(self):
        """Registration verification email originates from support@humatron.me with valid link."""
        unverified_user = User.objects.create_user(
            username='newuser@humatron.me',
            email='newuser@humatron.me',
            password='NewUserPassword123!',
            is_active=False,
            is_email_verified=False
        )
        success = EmailService.send_verification_email(unverified_user)
        self.assertTrue(success)
        self.assertEqual(len(mail.outbox), 1)

        sent_email = mail.outbox[0]
        self.assertIn("support@humatron.me", sent_email.from_email)
        self.assertEqual(sent_email.to, ['newuser@humatron.me'])
        self.assertIn("verify-email", sent_email.body)
        self.assertIn("Humatron", sent_email.subject)

    def test_password_reset_email_sent_from_support_and_does_not_leak_account(self):
        """Password reset email originates from support@humatron.me and response does not leak existence."""
        # 1. Request for existing user
        response = self.client.post(reverse('accounts:password_reset'), {'email': 'user@humatron.me'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)

        sent_email = mail.outbox[0]
        self.assertIn("support@humatron.me", sent_email.from_email)
        self.assertEqual(sent_email.to, ['user@humatron.me'])
        self.assertIn("reset", sent_email.body)

        # 2. Request for non-existent user - redirects same way without error (no account leakage)
        mail.outbox = []
        response_nonexistent = self.client.post(reverse('accounts:password_reset'), {'email': 'nonexistent@humatron.me'})
        self.assertEqual(response_nonexistent.status_code, 302)
        # No email sent for non-existent user, but user sees the identical confirmation page
        self.assertEqual(len(mail.outbox), 0)

    def test_payment_received_email_originates_from_support(self):
        """Payment confirmation emails are sent from support@humatron.me."""
        payment = Payment.objects.create(
            user=self.user,
            provider=Payment.PROVIDER_PAYPAL,
            transaction_id='PAYPAL-TEST-TX-101',
            plan=self.plan,
            amount=Decimal('50.00'),
            currency='USD',
            status=Payment.STATUS_VERIFIED
        )
        success = EmailService.send_payment_received_email(self.user, payment)
        self.assertTrue(success)
        self.assertEqual(len(mail.outbox), 1)

        sent_email = mail.outbox[0]
        self.assertIn("support@humatron.me", sent_email.from_email)
        self.assertEqual(sent_email.to, ['user@humatron.me'])
        self.assertIn("PAYPAL-TEST-TX-101", sent_email.body)

    def test_subscription_notifications_originate_from_support(self):
        """Subscription activation and expiration emails originate from support@humatron.me."""
        sub = Subscription.objects.create(
            user=self.user,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            pdf_limit=200,
            payment_method='PayPal'
        )

        # 1. Activation
        EmailService.send_subscription_activated_email(self.user, sub)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("support@humatron.me", mail.outbox[0].from_email)

        # 2. Expired
        mail.outbox = []
        EmailService.send_subscription_expired_email(self.user, sub)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("support@humatron.me", mail.outbox[0].from_email)

    def test_student_verification_notifications_originate_from_support(self):
        """Student verification approval/rejection emails originate from support@humatron.me."""
        EmailService.send_student_verification_approved_email(self.user)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("support@humatron.me", mail.outbox[0].from_email)
        self.assertIn("25%", mail.outbox[0].body)

        mail.outbox = []
        EmailService.send_student_verification_rejected_email(self.user, "Document blurry")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("support@humatron.me", mail.outbox[0].from_email)
        self.assertIn("Document blurry", mail.outbox[0].body)

    def test_pdf_processing_notifications_originate_from_support(self):
        """PDF completion emails originate from support@humatron.me."""
        job = PDFProcessingJob.objects.create(
            user=self.user,
            original_filename='test_invoice.pdf',
            stored_filename='test_stored.pdf',
            processed_filename='test_processed.pdf',
            page_count=5,
            input_size=1024,
            output_size=2048,
            status=PDFProcessingJob.STATUS_COMPLETED
        )
        EmailService.send_pdf_completed_email(self.user, job, "https://humatron.me/pdf/download/123/")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("support@humatron.me", mail.outbox[0].from_email)
        self.assertIn("test_invoice.pdf", mail.outbox[0].body)

    def test_contact_form_admin_notification_routed_correctly(self):
        """
        Contact form notification is sent TO admin@humatron.me,
        FROM contact@humatron.me, with user's submitted email in Reply-To header.
        Never allows visitor email as SMTP From.
        """
        contact_msg = ContactMessage.objects.create(
            name="Abebe Inquirer",
            email="abebe@example.com",
            subject="Partnership Inquiry",
            message="Hello Humatron team, I would like to partner with you.",
            ip_address="127.0.0.1"
        )

        success = EmailService.send_admin_contact_notification(contact_msg)
        self.assertTrue(success)
        self.assertEqual(len(mail.outbox), 1)

        sent_email = mail.outbox[0]
        # Admin recipient
        self.assertEqual(sent_email.to, ['admin@humatron.me'])
        # Sent FROM contact mailbox
        self.assertIn("contact@humatron.me", sent_email.from_email)
        # Visitor email placed in Reply-To, NOT in From
        self.assertEqual(sent_email.reply_to, ['abebe@example.com'])
        self.assertNotEqual(sent_email.from_email, 'abebe@example.com')

    def test_credential_sanitization_prevents_password_leakage(self):
        """sanitize_email_error scrubs passwords and connection tokens from error strings."""
        dirty_error = (
            "SMTPAuthenticationError: (535, b'5.7.8 Error: authentication failed: "
            "password=SuperSecretAppPassword123, user=support@humatron.me')"
        )
        clean_error = sanitize_email_error(dirty_error)
        self.assertNotIn("SuperSecretAppPassword123", clean_error)
        self.assertIn("[REDACTED]", clean_error)

    def test_admin_smtp_test_tool_requires_staff_authentication(self):
        """Unauthenticated and non-staff users cannot access the SMTP test tool."""
        test_url = reverse('admin:notifications_smtp_test')

        # 1. Anonymous user redirected to admin login
        anon_resp = self.client.get(test_url)
        self.assertEqual(anon_resp.status_code, 302)

        # 2. Normal non-staff user redirected or forbidden by admin site
        self.client.force_login(self.user)
        non_staff_resp = self.client.get(test_url)
        self.assertIn(non_staff_resp.status_code, [302, 403])

        # 3. Staff administrator allowed (200)
        self.client.force_login(self.admin_user)
        staff_resp = self.client.get(test_url)
        self.assertEqual(staff_resp.status_code, 200)
        self.assertIn("Humatron SMTP Test Tool", staff_resp.content.decode('utf-8'))

    def test_admin_smtp_test_execution_dispatches_test_email(self):
        """Admin SMTP test sends test email to specified recipient without exposing secrets."""
        self.client.force_login(self.admin_user)
        test_url = reverse('admin:notifications_smtp_test')

        response = self.client.post(test_url, {
            'recipient_email': 'admin@humatron.me',
            'mailbox': 'support'
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

        sent_email = mail.outbox[0]
        self.assertEqual(sent_email.to, ['admin@humatron.me'])
        self.assertIn("Humatron SMTP Test", sent_email.subject)
        self.assertIn("support@humatron.me", sent_email.from_email)
