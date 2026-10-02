import base64
import json
import time
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes

from subscriptions.models import SubscriptionPlan, Subscription
from payments.models import Payment
from payments.services import PaymentService
from payments.binance_service import BinancePayService

User = get_user_model()


class BinancePayTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Generate real RSA test key pair for webhook cryptographic verification tests
        cls.test_private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )
        cls.test_public_pem = cls.test_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')
        cls.test_cert_sn = "TEST_CERT_SERIAL_001"

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='crypto_user@humatron.me',
            email='crypto_user@humatron.me',
            password='StrongPassword123!',
            is_active=True,
            is_email_verified=True,
            country='United States'
        )
        self.plan = SubscriptionPlan.objects.create(
            name='Enterprise',
            code='enterprise',
            price=Decimal('100.00'),
            currency='USD',
            duration_days=30,
            pdf_limit=100
        )

    def _generate_valid_webhook_headers(self, raw_body_str):
        timestamp = str(int(time.time() * 1000))
        nonce = "abcdefghijklmnopqrstuvwxyz123456"
        payload_to_sign = f"{timestamp}\n{nonce}\n{raw_body_str}\n"

        signature = self.test_private_key.sign(
            payload_to_sign.encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        sig_b64 = base64.b64encode(signature).decode('utf-8')

        return {
            'HTTP_BINANCEPAY_TIMESTAMP': timestamp,
            'HTTP_BINANCEPAY_NONCE': nonce,
            'HTTP_BINANCEPAY_CERTIFICATE_SN': self.test_cert_sn,
            'HTTP_BINANCEPAY_SIGNATURE': sig_b64,
        }

    # 1. Order Creation Tests
    def test_initiate_binance_payment_creates_pending_record(self):
        success, msg, payment = PaymentService.initiate_binance_payment(
            user=self.user,
            plan=self.plan
        )
        self.assertTrue(success)
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, Payment.STATUS_PENDING)
        self.assertEqual(payment.provider, Payment.PROVIDER_BINANCE)
        self.assertEqual(payment.amount, Decimal('100.00'))
        self.assertEqual(payment.currency, 'USDT')
        self.assertTrue(payment.merchant_trade_no.startswith('HP'))
        self.assertTrue(bool(payment.checkout_url))

    def test_unverified_email_cannot_initiate_binance_payment(self):
        self.user.is_email_verified = False
        self.user.save(update_fields=['is_email_verified'])

        success, msg, payment = PaymentService.initiate_binance_payment(
            user=self.user,
            plan=self.plan
        )
        self.assertFalse(success)
        self.assertIn("Email verification is required", msg)
        self.assertIsNone(payment)

    def test_inactive_plan_cannot_be_purchased(self):
        self.plan.active = False
        self.plan.save(update_fields=['active'])

        success, msg, payment = PaymentService.initiate_binance_payment(
            user=self.user,
            plan=self.plan
        )
        self.assertFalse(success)
        self.assertIn("not active", msg)

    # 2. Webhook Signature Verification Tests
    @patch.object(BinancePayService, 'query_certificates')
    def test_valid_webhook_signature_accepted(self, mock_certs):
        mock_certs.return_value = {self.test_cert_sn: self.test_public_pem}

        raw_body = json.dumps({
            "bizType": "PAY",
            "bizId": 123456789,
            "bizStatus": "PAY_SUCCESS",
            "data": json.dumps({
                "merchantTradeNo": "HPTEST1234",
                "totalFee": "100.00",
                "currency": "USDT"
            })
        })
        headers = self._generate_valid_webhook_headers(raw_body)
        raw_headers = {
            'BinancePay-Timestamp': headers['HTTP_BINANCEPAY_TIMESTAMP'],
            'BinancePay-Nonce': headers['HTTP_BINANCEPAY_NONCE'],
            'BinancePay-Certificate-SN': headers['HTTP_BINANCEPAY_CERTIFICATE_SN'],
            'BinancePay-Signature': headers['HTTP_BINANCEPAY_SIGNATURE'],
        }

        valid, msg = BinancePayService.verify_webhook_signature(
            headers=raw_headers,
            raw_body_bytes=raw_body.encode('utf-8')
        )
        self.assertTrue(valid)
        self.assertEqual(msg, "Signature valid")

    @patch.object(BinancePayService, 'query_certificates')
    def test_tampered_webhook_body_rejected(self, mock_certs):
        mock_certs.return_value = {self.test_cert_sn: self.test_public_pem}

        original_body = json.dumps({"test": "data"})
        headers = self._generate_valid_webhook_headers(original_body)
        raw_headers = {
            'BinancePay-Timestamp': headers['HTTP_BINANCEPAY_TIMESTAMP'],
            'BinancePay-Nonce': headers['HTTP_BINANCEPAY_NONCE'],
            'BinancePay-Certificate-SN': headers['HTTP_BINANCEPAY_CERTIFICATE_SN'],
            'BinancePay-Signature': headers['HTTP_BINANCEPAY_SIGNATURE'],
        }

        # Tampered body
        tampered_body = json.dumps({"test": "tampered_data"})
        valid, msg = BinancePayService.verify_webhook_signature(
            headers=raw_headers,
            raw_body_bytes=tampered_body.encode('utf-8')
        )
        self.assertFalse(valid)
        self.assertIn("Invalid signature", msg)

    # 3. Webhook Execution and Subscription Activation
    @patch.object(BinancePayService, 'query_certificates')
    def test_webhook_pay_success_activates_subscription(self, mock_certs):
        mock_certs.return_value = {self.test_cert_sn: self.test_public_pem}

        # Create pending payment
        _, _, payment = PaymentService.initiate_binance_payment(self.user, self.plan)
        trade_no = payment.merchant_trade_no

        webhook_data = {
            "bizType": "PAY",
            "bizId": "BINANCE_ORDER_999",
            "bizStatus": "PAY_SUCCESS",
            "data": json.dumps({
                "merchantTradeNo": trade_no,
                "totalFee": "100.00",
                "currency": "USDT",
                "transactTime": 1727690000000
            })
        }
        raw_body = json.dumps(webhook_data)
        headers = self._generate_valid_webhook_headers(raw_body)

        response = self.client.post(
            reverse('payments:binance_webhook'),
            data=raw_body,
            content_type='application/json',
            **headers
        )

        self.assertEqual(response.status_code, 200)
        res_json = response.json()
        self.assertEqual(res_json.get('returnCode'), 'SUCCESS')

        # Verify DB payment state
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.STATUS_VERIFIED)
        self.assertIsNotNone(payment.verified_at)
        self.assertIsNotNone(payment.subscription)
        self.assertEqual(payment.subscription.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(payment.subscription.user, self.user)
        self.assertEqual(payment.subscription.pdf_limit, 100)

    # 4. Idempotency Test: Repeated Webhook Must Not Create Duplicate Subscription
    @patch.object(BinancePayService, 'query_certificates')
    def test_duplicate_webhook_is_idempotent(self, mock_certs):
        mock_certs.return_value = {self.test_cert_sn: self.test_public_pem}

        _, _, payment = PaymentService.initiate_binance_payment(self.user, self.plan)
        trade_no = payment.merchant_trade_no

        webhook_data = {
            "bizType": "PAY",
            "bizId": "BINANCE_ORDER_IDEMPOTENT",
            "bizStatus": "PAY_SUCCESS",
            "data": json.dumps({
                "merchantTradeNo": trade_no,
                "totalFee": "100.00",
                "currency": "USDT"
            })
        }
        raw_body = json.dumps(webhook_data)
        headers = self._generate_valid_webhook_headers(raw_body)

        # First call
        resp1 = self.client.post(reverse('payments:binance_webhook'), data=raw_body, content_type='application/json', **headers)
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(Subscription.objects.filter(user=self.user, status=Subscription.STATUS_ACTIVE).count(), 1)

        # Second call (replay / duplicate webhook)
        resp2 = self.client.post(reverse('payments:binance_webhook'), data=raw_body, content_type='application/json', **headers)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json().get('returnCode'), 'SUCCESS')

        # Must still be exactly 1 active subscription
        self.assertEqual(Subscription.objects.filter(user=self.user, status=Subscription.STATUS_ACTIVE).count(), 1)

    # 5. Underpayment / Amount mismatch rejected
    def test_underpaid_binance_order_rejected(self):
        _, _, payment = PaymentService.initiate_binance_payment(self.user, self.plan)
        trade_no = payment.merchant_trade_no

        webhook_payload = {
            "bizType": "PAY",
            "bizStatus": "PAY_SUCCESS",
            "data": json.dumps({
                "merchantTradeNo": trade_no,
                "totalFee": "50.00",  # Expected 100.00
                "currency": "USDT"
            })
        }

        success, msg, _ = PaymentService.verify_and_activate_binance(
            merchant_trade_no=trade_no,
            webhook_payload=webhook_payload,
            query_binance=False
        )
        self.assertFalse(success)
        self.assertIn("Underpaid", msg)

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.STATUS_REJECTED)
        self.assertFalse(Subscription.objects.filter(user=self.user, status=Subscription.STATUS_ACTIVE).exists())

    # 6. Currency mismatch rejected
    def test_currency_mismatch_rejected(self):
        _, _, payment = PaymentService.initiate_binance_payment(self.user, self.plan)
        trade_no = payment.merchant_trade_no

        webhook_payload = {
            "bizType": "PAY",
            "bizStatus": "PAY_SUCCESS",
            "data": json.dumps({
                "merchantTradeNo": trade_no,
                "totalFee": "100.00",
                "currency": "EUR"  # Expected USDT
            })
        }

        success, msg, _ = PaymentService.verify_and_activate_binance(
            merchant_trade_no=trade_no,
            webhook_payload=webhook_payload,
            query_binance=False
        )
        self.assertFalse(success)
        self.assertIn("Currency mismatch", msg)

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.STATUS_REJECTED)

    # 7. Order Status API and Authorization
    @patch.object(BinancePayService, 'query_order')
    def test_order_status_api_object_permission(self, mock_query):
        mock_query.return_value = (True, "Query successful", {'status': 'PENDING'})
        _, _, payment = PaymentService.initiate_binance_payment(self.user, self.plan)

        other_user = User.objects.create_user(
            username='other@humatron.me',
            email='other@humatron.me',
            password='OtherPassword123!',
            is_active=True
        )

        # Other user cannot access this user's payment status
        self.client.force_login(other_user)
        resp = self.client.get(reverse('payments:binance_status', args=[payment.merchant_trade_no]))
        self.assertEqual(resp.status_code, 404)

        # Owner can access
        self.client.force_login(self.user)
        resp2 = self.client.get(reverse('payments:binance_status', args=[payment.merchant_trade_no]))
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json().get('status'), Payment.STATUS_PENDING)
