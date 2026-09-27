from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from accounts.tokens import email_verification_token

User = get_user_model()


class AuthenticationTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_registration_creates_unverified_account_and_sends_token(self):
        url = reverse('accounts:register')
        data = {
            'first_name': 'Ezra',
            'last_name': 'Tester',
            'email': 'ezra@humatron.me',
            'phone_number': '+251911223344',
            'country': 'Ethiopia',
            'job_title': 'Developer',
            'job_title_other': '',
            'sex': 'male',
            'password': 'StrongPassword123!',
            'password_confirm': 'StrongPassword123!',
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Verify Your Email Address')

        user = User.objects.get(email='ezra@humatron.me')
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_email_verified)
        self.assertFalse(user.trial_used)

    def test_weak_password_rejected(self):
        url = reverse('accounts:register')
        data = {
            'first_name': 'Ezra',
            'last_name': 'Tester',
            'email': 'weak@humatron.me',
            'phone_number': '+251911223344',
            'country': 'Ethiopia',
            'job_title': 'Developer',
            'sex': 'male',
            'password': '123',  # Too short, numeric
            'password_confirm': '123',
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email='weak@humatron.me').exists())

    def test_email_verification_activates_account(self):
        user = User.objects.create_user(
            username='verify@humatron.me',
            email='verify@humatron.me',
            password='StrongPassword123!',
            is_active=False,
            is_email_verified=False
        )
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = email_verification_token.make_token(user)

        verify_url = reverse('accounts:verify_email', kwargs={'uidb64': uid, 'token': token})
        response = self.client.get(verify_url, follow=True)
        self.assertEqual(response.status_code, 200)

        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)
        self.assertTrue(user.is_active)

        # Single-use verification: second attempt fails
        response2 = self.client.get(verify_url)
        self.assertContains(response2, 'Verification Failed')

    def test_unverified_user_cannot_login(self):
        user = User.objects.create_user(
            username='unverified@humatron.me',
            email='unverified@humatron.me',
            password='StrongPassword123!',
            is_active=False,
            is_email_verified=False
        )
        login_url = reverse('accounts:login')
        response = self.client.post(login_url, {
            'email': 'unverified@humatron.me',
            'password': 'StrongPassword123!'
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please verify your email address')
        self.assertFalse('_auth_user_id' in self.client.session)

    def test_verified_user_login_and_logout(self):
        user = User.objects.create_user(
            username='verified@humatron.me',
            email='verified@humatron.me',
            password='StrongPassword123!',
            is_active=True,
            is_email_verified=True
        )
        login_url = reverse('accounts:login')
        response = self.client.post(login_url, {
            'email': 'verified@humatron.me',
            'password': 'StrongPassword123!'
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(int(self.client.session['_auth_user_id']), user.id)

        # Logout
        logout_url = reverse('accounts:logout')
        logout_response = self.client.get(logout_url, follow=True)
        self.assertEqual(logout_response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_password_reset_avoids_account_enumeration(self):
        reset_url = reverse('accounts:password_reset')
        # Submit non-existent email
        response = self.client.post(reset_url, {'email': 'nonexistent@humatron.me'}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Check Your Email')
