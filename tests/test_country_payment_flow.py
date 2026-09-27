from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from subscriptions.models import SubscriptionPlan, Subscription
from payments.models import Payment
from payments.services import PaymentService

User = get_user_model()


class CountryPaymentFlowTests(TestCase):
    """
    Tests for Sections 1-6 of the Humatron Specification Modifications:
    - Public hiding of ETB, Telebirr, and country-specific instructions
    - Server-determined payment method based on authenticated user's registered country
    - Strict Ethiopia -> Telebirr and Non-Ethiopia -> PayPal isolation
    """

    def setUp(self):
        self.client = Client()
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

        self.ethiopia_user = User.objects.create_user(
            username='ethiopia@humatron.me',
            email='ethiopia@humatron.me',
            password='TestPassword123!',
            country='Ethiopia',
            is_active=True,
            is_email_verified=True
        )

        self.us_user = User.objects.create_user(
            username='usa@humatron.me',
            email='usa@humatron.me',
            password='TestPassword123!',
            country='United States',
            is_active=True,
            is_email_verified=True
        )

    def test_anonymous_visitor_does_not_see_etb_or_telebirr_on_home(self):
        """Anonymous visitors must NOT see ETB, Birr, or Telebirr on home page."""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertNotIn('ETB', content)
        self.assertNotIn('Birr', content)
        self.assertNotIn('Telebirr', content)

    def test_anonymous_visitor_does_not_see_etb_or_telebirr_on_plans(self):
        """Anonymous visitors must NOT see ETB, Birr, or Telebirr on public plans page."""
        response = self.client.get(reverse('subscriptions:plans'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertNotIn('Telebirr', content)
        self.assertNotIn('ETB', content)
        self.assertNotIn('Birr', content)
        self.assertNotIn('PayPal', content)

    def test_anonymous_user_cannot_access_checkout_directly(self):
        """Unauthenticated visitor is redirected to login from checkout."""
        url = reverse('payments:checkout', args=['professional'])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_anonymous_user_cannot_access_telebirr_verify(self):
        """Unauthenticated visitor is redirected from Telebirr verification."""
        url = reverse('payments:verify_telebirr', args=['professional'])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_ethiopian_user_checkout_shows_telebirr_and_hides_paypal(self):
        """Authenticated Ethiopian user sees Telebirr instructions and NOT PayPal instructions."""
        self.client.force_login(self.ethiopia_user)
        response = self.client.get(reverse('payments:checkout', args=['professional']))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('Telebirr', content)
        self.assertIn('6750.00', content)
        self.assertIn('Proceed to Telebirr Message Verification', content)
        # Should not show PayPal checkout option
        self.assertNotIn('Default Payment Method', content)
        self.assertNotIn('Pay securely with your PayPal account', content)

    def test_non_ethiopian_user_checkout_shows_paypal_and_hides_telebirr(self):
        """Authenticated non-Ethiopian user sees PayPal and NOT Ethiopian payment instructions."""
        self.client.force_login(self.us_user)
        response = self.client.get(reverse('payments:checkout', args=['professional']))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('PayPal', content)
        self.assertIn('50.00', content)
        self.assertNotIn('Proceed to Telebirr Message Verification', content)
        self.assertNotIn('Merchant Name:', content)
        self.assertNotIn('6750.00 ETB', content)

    def test_non_ethiopian_user_forbidden_from_telebirr_endpoint(self):
        """Non-Ethiopian users are strictly forbidden (403) from Telebirr verification endpoint."""
        self.client.force_login(self.us_user)
        response = self.client.get(reverse('payments:verify_telebirr', args=['professional']))
        self.assertEqual(response.status_code, 403)

    def test_telebirr_service_verifies_ethiopian_country_constraint(self):
        """PaymentService.verify_and_activate_telebirr rejects non-Ethiopian accounts."""
        raw_msg = (
            "You have transferred 6750.00 ETB to Humatron Technologies (0911000000). "
            "Transaction number TX_USA_USER on 2026-09-27."
        )
        success, msg, payment = PaymentService.verify_and_activate_telebirr(
            user=self.us_user,
            plan=self.plan,
            raw_message=raw_msg
        )
        self.assertFalse(success)
        self.assertIn("only permitted for verified accounts registered in Ethiopia", msg)
