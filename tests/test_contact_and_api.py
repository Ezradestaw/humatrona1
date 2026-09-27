import io
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from contact.models import ContactMessage
from subscriptions.models import SubscriptionPlan
from pdf_processor.models import PDFProcessingJob

User = get_user_model()


class ContactAndAPITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='apiuser@humatron.me',
            email='apiuser@humatron.me',
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
            max_pages_per_pdf=100,
            active=True
        )

    def test_contact_form_submission_success(self):
        url = reverse('contact:index')
        data = {
            'name': 'Abebe Kebede',
            'email': 'abebe@example.com',
            'subject': 'Enterprise Quote',
            'message': 'Inquiry regarding bulk conversion workflow.',
            'website': '',  # Honeypot must be empty
        }
        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ContactMessage.objects.filter(email='abebe@example.com').exists())
        msg = ContactMessage.objects.get(email='abebe@example.com')
        self.assertEqual(msg.subject, 'Enterprise Quote')
        self.assertFalse(msg.is_read)

    def test_contact_form_honeypot_rejects_bots(self):
        url = reverse('contact:index')
        data = {
            'name': 'Spambot',
            'email': 'spam@bot.com',
            'subject': 'Spam Subject',
            'message': 'Buy cheap crypto now',
            'website': 'https://spamurl.com',  # Honeypot filled by bot
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        # Message must NOT be saved to database
        self.assertFalse(ContactMessage.objects.filter(email='spam@bot.com').exists())

    def test_api_plans_endpoint(self):
        url = reverse('api:subscription_plans')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)
        self.assertGreaterEqual(len(response.json()), 1)

    def test_api_login_and_profile(self):
        login_url = reverse('api:auth_login')
        resp = self.client.post(login_url, {
            'email': 'apiuser@humatron.me',
            'password': 'StrongPassword123!'
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('user', resp.json())

        # Profile GET
        profile_url = reverse('api:profile')
        prof_resp = self.client.get(profile_url)
        self.assertEqual(prof_resp.status_code, 200)
        self.assertEqual(prof_resp.json()['email'], 'apiuser@humatron.me')

    def test_api_pdf_process_requires_auth(self):
        anon_client = Client()
        url = reverse('api:pdf_process')
        resp = anon_client.post(url, {})
        self.assertEqual(resp.status_code, 403)
