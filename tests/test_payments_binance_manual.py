import io
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import mail
from django.contrib.auth import get_user_model
from subscriptions.models import SubscriptionPlan, Subscription
from payments.models import Payment, BinanceManualPaymentSettings
from payments.services import PaymentService

User = get_user_model()


class BinanceManualPaymentTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Admin user
        self.admin_user = User.objects.create_superuser(
            username='admin@humatron.me',
            email='admin@humatron.me',
            password='AdminPassword123!'
        )

        # Regular customer user
        self.user = User.objects.create_user(
            username='customer@humatron.me',
            email='customer@humatron.me',
            password='CustomerPassword123!',
            country='Germany',
            is_active=True,
            is_email_verified=True
        )

        # Other customer user (for IDOR / ownership testing)
        self.other_user = User.objects.create_user(
            username='other@humatron.me',
            email='other@humatron.me',
            password='OtherPassword123!',
            country='France',
            is_active=True,
            is_email_verified=True
        )

        # Plan
        self.plan = SubscriptionPlan.objects.create(
            name='Professional',
            code='professional',
            price=Decimal('50.00'),
            currency='USD',
            duration_days=30,
            pdf_limit=50,
            max_file_size_mb=25,
            active=True
        )

        # Configure manual settings
        self.settings = BinanceManualPaymentSettings.get_settings()
        self.settings.enabled = True
        self.settings.receiving_identifier = "87654321"
        self.settings.receiving_identifier_type = BinanceManualPaymentSettings.IDENTIFIER_TYPE_UID
        self.settings.save()

    def test_anonymous_cannot_access_manual_checkout(self):
        """Unauthenticated visitor is redirected to login."""
        url = reverse('payments:binance_manual_checkout', args=['professional'])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_anonymous_cannot_access_payment_status(self):
        """Unauthenticated visitor cannot view status page."""
        url = reverse('payments:binance_manual_status', args=[999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_authenticated_user_sees_manual_checkout_page(self):
        """Authenticated user sees Binance manual instructions, receiving UID, and amount."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('payments:binance_manual_checkout', args=['professional']))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn("BINANCE MANUAL PAYMENT", content)
        self.assertIn("87654321", content)
        self.assertIn("50.00", content)
        self.assertIn("USDT", content)
        self.assertIn("Binance UID", content)
        self.assertIn("Send Payment via Binance", content)
        self.assertIn("Submit Your Transaction Information", content)

    def test_valid_manual_payment_submission_creates_pending_payment(self):
        """User submission creates a PENDING payment record and does NOT activate subscription."""
        self.client.force_login(self.user)
        mail.outbox.clear()

        url = reverse('payments:binance_manual_checkout', args=['professional'])
        data = {
            'transaction_id': 'TX-BINANCE-1001',
            'sender_identifier': 'UID-SENDER-88',
            'amount': '50.00',
            'note': 'Transferred via Binance Pay internal transfer',
        }
        response = self.client.post(url, data)
        
        # Payment must exist in DB
        payment = Payment.objects.filter(transaction_id='TX-BINANCE-1001').first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.user, self.user)
        self.assertEqual(payment.plan, self.plan)
        self.assertEqual(payment.amount, Decimal('50.00'))
        self.assertEqual(payment.currency, 'USDT')
        self.assertEqual(payment.status, Payment.STATUS_PENDING)
        self.assertEqual(payment.payment_method, Payment.METHOD_BINANCE_MANUAL)
        self.assertEqual(payment.sender_identifier, 'UID-SENDER-88')

        # Subscription must NOT be activated yet
        self.assertIsNone(payment.subscription)
        self.assertFalse(Subscription.objects.filter(user=self.user, status=Subscription.STATUS_ACTIVE).exists())

        # Redirected to status page
        self.assertRedirects(response, reverse('payments:binance_manual_status', args=[payment.id]))

        # Confirmation email dispatched
        self.assertTrue(len(mail.outbox) >= 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, [self.user.email])
        self.assertIn("Binance Payment Submitted", sent.subject)
        self.assertIn("TX-BINANCE-1001", sent.body)

    def test_submission_with_underpaid_amount_rejected(self):
        """Submitting less than the required plan amount is rejected."""
        self.client.force_login(self.user)
        url = reverse('payments:binance_manual_checkout', args=['professional'])
        data = {
            'transaction_id': 'TX-UNDERPAID-01',
            'sender_identifier': 'UID-SENDER-01',
            'amount': '30.00',  # Required is 50.00
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn("less than the required plan amount", content)
        self.assertFalse(Payment.objects.filter(transaction_id='TX-UNDERPAID-01').exists())

    def test_submission_with_missing_transaction_id_rejected(self):
        """Missing required transaction ID is rejected."""
        self.client.force_login(self.user)
        url = reverse('payments:binance_manual_checkout', args=['professional'])

        response = self.client.post(url, {
            'transaction_id': '',
            'amount': '50.00'
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Payment.objects.filter(transaction_id='').exists())

    def test_submission_with_only_transaction_number_succeeds(self):
        """In Binance, only transaction number is necessary (no screenshot needed)."""
        self.client.force_login(self.user)
        url = reverse('payments:binance_manual_checkout', args=['professional'])
        response = self.client.post(url, {
            'transaction_id': 'TX-ONLY-NUMBER-101',
        })
        payment = Payment.objects.filter(transaction_id='TX-ONLY-NUMBER-101').first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, Payment.STATUS_PENDING)
        self.assertEqual(payment.amount, Decimal('50.00'))
        self.assertRedirects(response, reverse('payments:binance_manual_status', args=[payment.id]))

    def test_duplicate_transaction_id_submission_prevented(self):
        """Submitting the same transaction ID twice is blocked by validation."""
        self.client.force_login(self.user)
        url = reverse('payments:binance_manual_checkout', args=['professional'])

        # First submission
        self.client.post(url, {
            'transaction_id': 'TX-DUP-CHECK',
            'sender_identifier': 'UID-01',
            'amount': '50.00'
        })
        self.assertTrue(Payment.objects.filter(transaction_id='TX-DUP-CHECK').exists())

        # Second submission with same transaction ID
        response = self.client.post(url, {
            'transaction_id': 'TX-DUP-CHECK',
            'sender_identifier': 'UID-02',
            'amount': '50.00'
        })
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn("already been submitted or processed", content)

    def test_file_upload_validation_accepts_valid_image(self):
        """Valid PNG proof file is accepted and stored."""
        self.client.force_login(self.user)
        url = reverse('payments:binance_manual_checkout', args=['professional'])

        # Minimal valid 1x1 PNG
        png_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82'
        uploaded_file = SimpleUploadedFile("proof.png", png_bytes, content_type="image/png")

        data = {
            'transaction_id': 'TX-WITH-PROOF-01',
            'sender_identifier': 'UID-PROOF-USER',
            'amount': '50.00',
            'proof_file': uploaded_file,
        }
        response = self.client.post(url, data)
        payment = Payment.objects.filter(transaction_id='TX-WITH-PROOF-01').first()
        self.assertIsNotNone(payment)
        self.assertTrue(bool(payment.proof_file))

    def test_file_upload_validation_rejects_disallowed_extension(self):
        """Executable or script file extensions are rejected."""
        self.client.force_login(self.user)
        url = reverse('payments:binance_manual_checkout', args=['professional'])

        bad_file = SimpleUploadedFile("malicious.sh", b"echo hack", content_type="text/x-shellscript")
        data = {
            'transaction_id': 'TX-BAD-FILE',
            'sender_identifier': 'UID-01',
            'amount': '50.00',
            'proof_file': bad_file,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn("is not permitted", content)
        self.assertFalse(Payment.objects.filter(transaction_id='TX-BAD-FILE').exists())

    def test_file_upload_validation_rejects_oversized_file(self):
        """Files larger than 5 MB are rejected."""
        self.client.force_login(self.user)
        url = reverse('payments:binance_manual_checkout', args=['professional'])

        large_bytes = b'0' * (5 * 1024 * 1024 + 1024)  # > 5 MB
        large_file = SimpleUploadedFile("large_receipt.jpg", large_bytes, content_type="image/jpeg")
        data = {
            'transaction_id': 'TX-LARGE-FILE',
            'sender_identifier': 'UID-01',
            'amount': '50.00',
            'proof_file': large_file,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn("exceeds maximum allowed size of 5 MB", content)
        self.assertFalse(Payment.objects.filter(transaction_id='TX-LARGE-FILE').exists())

    def test_payment_status_user_ownership_enforced(self):
        """Users can only view their own payment status page (IDOR protection)."""
        payment = Payment.objects.create(
            user=self.user,
            provider=Payment.PROVIDER_BINANCE,
            payment_method=Payment.METHOD_BINANCE_MANUAL,
            transaction_id='TX-OWNERSHIP-101',
            amount=Decimal('50.00'),
            currency='USDT',
            status=Payment.STATUS_PENDING,
            plan=self.plan
        )

        # Other user cannot access this payment
        self.client.force_login(self.other_user)
        resp_forbidden = self.client.get(reverse('payments:binance_manual_status', args=[payment.id]))
        self.assertEqual(resp_forbidden.status_code, 404)

        # Owner user can access and sees status
        self.client.force_login(self.user)
        resp_owner = self.client.get(reverse('payments:binance_manual_status', args=[payment.id]))
        self.assertEqual(resp_owner.status_code, 200)
        content = resp_owner.content.decode('utf-8')
        self.assertIn("Your Binance payment is being reviewed", content)
        self.assertIn("TX-OWNERSHIP-101", content)

    def test_admin_approval_activates_subscription_and_sends_email(self):
        """Admin approval marks payment APPROVED, activates subscription, and emails user."""
        payment = Payment.objects.create(
            user=self.user,
            provider=Payment.PROVIDER_BINANCE,
            payment_method=Payment.METHOD_BINANCE_MANUAL,
            transaction_id='TX-APPROVE-TEST',
            amount=Decimal('50.00'),
            currency='USDT',
            status=Payment.STATUS_PENDING,
            plan=self.plan,
            payment_country=self.user.country
        )

        mail.outbox.clear()

        # Approve as admin
        success, msg, payment_approved = PaymentService.approve_binance_manual_payment(
            payment_id_or_obj=payment,
            admin_user=self.admin_user
        )
        self.assertTrue(success)
        payment.refresh_from_db()

        self.assertEqual(payment.status, Payment.STATUS_APPROVED)
        self.assertIsNotNone(payment.reviewed_at)
        self.assertEqual(payment.reviewed_by, self.admin_user)
        self.assertIsNotNone(payment.subscription)

        # Check subscription
        sub = payment.subscription
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(sub.user, self.user)
        self.assertEqual(sub.plan, self.plan)
        self.assertEqual(sub.pdf_limit, 50)
        self.assertTrue(sub.is_valid)

        # Check approval email sent
        self.assertTrue(len(mail.outbox) >= 1)
        sent_emails = [m for m in mail.outbox if "Approved" in m.subject]
        self.assertTrue(len(sent_emails) >= 1)
        self.assertIn("TX-APPROVE-TEST", sent_emails[0].body)

        # Check user-facing status page reflects approval
        self.client.force_login(self.user)
        resp = self.client.get(reverse('payments:binance_manual_status', args=[payment.id]))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Your payment has been approved and your subscription is active", content)

    def test_duplicate_admin_approval_is_idempotent(self):
        """Approving an already-approved payment does not duplicate subscription activation."""
        payment = Payment.objects.create(
            user=self.user,
            provider=Payment.PROVIDER_BINANCE,
            payment_method=Payment.METHOD_BINANCE_MANUAL,
            transaction_id='TX-IDEMPOTENT-01',
            amount=Decimal('50.00'),
            currency='USDT',
            status=Payment.STATUS_PENDING,
            plan=self.plan
        )

        # First approval
        success1, _, _ = PaymentService.approve_binance_manual_payment(payment, self.admin_user)
        self.assertTrue(success1)
        sub_count1 = Subscription.objects.filter(user=self.user).count()
        self.assertEqual(sub_count1, 1)

        # Second approval attempt
        success2, msg2, _ = PaymentService.approve_binance_manual_payment(payment, self.admin_user)
        self.assertTrue(success2)
        self.assertIn("already approved", msg2)
        sub_count2 = Subscription.objects.filter(user=self.user).count()
        self.assertEqual(sub_count2, 1)

    def test_admin_rejection_marks_rejected_and_sends_email(self):
        """Admin rejection marks payment REJECTED, records reason, sends email, and does not activate subscription."""
        payment = Payment.objects.create(
            user=self.user,
            provider=Payment.PROVIDER_BINANCE,
            payment_method=Payment.METHOD_BINANCE_MANUAL,
            transaction_id='TX-REJECT-01',
            amount=Decimal('50.00'),
            currency='USDT',
            status=Payment.STATUS_PENDING,
            plan=self.plan
        )

        mail.outbox.clear()

        rejection_reason = "Binance transaction hash not found on chain or in merchant portal."
        success, msg, _ = PaymentService.reject_binance_manual_payment(
            payment_id_or_obj=payment,
            admin_user=self.admin_user,
            reason=rejection_reason
        )
        self.assertTrue(success)
        payment.refresh_from_db()

        self.assertEqual(payment.status, Payment.STATUS_REJECTED)
        self.assertEqual(payment.rejection_reason, rejection_reason)
        self.assertEqual(payment.reviewed_by, self.admin_user)
        self.assertIsNone(payment.subscription)

        # Verify no active subscription was created
        self.assertFalse(Subscription.objects.filter(user=self.user, status=Subscription.STATUS_ACTIVE).exists())

        # Check rejection email sent
        sent_emails = [m for m in mail.outbox if "Update" in m.subject]
        self.assertTrue(len(sent_emails) >= 1)
        self.assertIn(rejection_reason, sent_emails[0].body)

        # Check user-facing status page reflects rejection and shows reason
        self.client.force_login(self.user)
        resp = self.client.get(reverse('payments:binance_manual_status', args=[payment.id]))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Your payment was rejected", content)
        self.assertIn(rejection_reason, content)

    def test_non_admin_cannot_approve_or_reject(self):
        """Regular user without staff permission cannot approve or reject payments."""
        payment = Payment.objects.create(
            user=self.user,
            provider=Payment.PROVIDER_BINANCE,
            payment_method=Payment.METHOD_BINANCE_MANUAL,
            transaction_id='TX-AUTH-TEST',
            amount=Decimal('50.00'),
            currency='USDT',
            status=Payment.STATUS_PENDING,
            plan=self.plan
        )

        # Customer attempts approval
        success_app, msg_app, _ = PaymentService.approve_binance_manual_payment(payment, self.other_user)
        self.assertFalse(success_app)
        self.assertIn("Administrator authorization is required", msg_app)

        # Customer attempts rejection
        success_rej, msg_rej, _ = PaymentService.reject_binance_manual_payment(payment, self.other_user, "fraud")
        self.assertFalse(success_rej)
        self.assertIn("Administrator authorization is required", msg_rej)

    def test_database_price_applied_on_manual_checkout(self):
        """Checkout pulls price directly from database plan with UID 1104715375."""
        self.settings.receiving_identifier = "1104715375"
        self.settings.save()
        self.client.force_login(self.user)
        url = reverse('payments:binance_manual_checkout', args=['professional'])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # 50.00 USDT from database plan
        self.assertIn("50.00", content)
        self.assertIn("1104715375", content)
        self.assertNotIn("Student", content)
        self.assertNotIn("student", content)

        # Submitting exact plan price succeeds
        resp_post = self.client.post(url, {
            'transaction_id': 'TX-EXACT-PRICE',
            'sender_identifier': 'UID-TEST-999',
            'amount': '50.00'
        })
        payment = Payment.objects.filter(transaction_id='TX-EXACT-PRICE').first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, Decimal('50.00'))
