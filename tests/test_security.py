from django.test import TestCase, Client
from django.urls import reverse
from django.core.cache import cache
from django.contrib.auth import get_user_model
from pdf_processor.models import PDFProcessingJob
from payments.models import Payment

User = get_user_model()


class SecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.userA = User.objects.create_user(
            username='userA@humatron.me',
            email='userA@humatron.me',
            password='StrongPassword123!',
            is_active=True,
            is_email_verified=True
        )
        self.userB = User.objects.create_user(
            username='userB@humatron.me',
            email='userB@humatron.me',
            password='StrongPassword123!',
            is_active=True,
            is_email_verified=True
        )

    def test_idor_protection_on_job_detail(self):
        jobA = PDFProcessingJob.objects.create(
            user=self.userA,
            original_filename='privateA.pdf',
            stored_filename='privateA.pdf',
            status=PDFProcessingJob.STATUS_COMPLETED
        )

        # User B attempts to access User A's job detail
        clientB = Client()
        clientB.force_login(self.userB)
        resp = clientB.get(reverse('pdf_processor:job_detail', kwargs={'job_id': jobA.id}))
        self.assertEqual(resp.status_code, 404, "User B must not access User A's job details.")

    def test_payment_history_isolation(self):
        Payment.objects.create(
            user=self.userA,
            provider='telebirr',
            transaction_id='TX_PRIV_A',
            amount=50.0,
            currency='USD',
            status=Payment.STATUS_VERIFIED
        )
        Payment.objects.create(
            user=self.userB,
            provider='paypal',
            transaction_id='TX_PRIV_B',
            amount=50.0,
            currency='USD',
            status=Payment.STATUS_VERIFIED
        )

        clientA = Client()
        clientA.force_login(self.userA)
        respA = clientA.get(reverse('payments:history'))
        self.assertEqual(respA.status_code, 200)
        self.assertContains(respA, 'TX_PRIV_A')
        self.assertNotContains(respA, 'TX_PRIV_B')

    def test_rate_limiting_middleware_enforcement(self):
        client = Client()
        reg_url = reverse('accounts:register')
        
        # Max 5 registrations per 10 mins configured
        for i in range(5):
            resp = client.post(reg_url, {'email': f'ratetest{i}@humatron.me'}, REMOTE_ADDR='198.51.100.42')
            # First 5 attempts return regular response (200 or form errors)
            self.assertNotEqual(resp.status_code, 429)

        # 6th attempt must trigger HTTP 429 Too Many Requests
        resp6 = client.post(reg_url, {'email': 'ratetest6@humatron.me'}, REMOTE_ADDR='198.51.100.42')
        self.assertEqual(resp6.status_code, 429)
        self.assertIn('Retry-After', resp6.headers)
