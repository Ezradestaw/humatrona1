import base64
import hashlib
import hmac
import json
import logging
import secrets
import string
import time
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

import requests
from django.conf import settings
from django.core.cache import cache
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger('humatron')


class BinancePayService:
    """
    Authoritative client for Binance Pay Merchant Open API (v3/v2).
    Follows official Binance Developer specifications:
    - Base URL: https://bpay.binanceapi.com
    - Outbound Request Signing: HMAC-SHA512
    - Inbound Webhook Verification: RSA-SHA256 with dynamic certificate resolution
    - Endpoints:
        * Create Order: POST /binancepay/openapi/v3/order
        * Query Order:  POST /binancepay/openapi/v2/order/query
        * Certificates: POST /binancepay/openapi/certificates
        * Refund Order: POST /binancepay/openapi/order/refund
    """

    CERTIFICATE_CACHE_KEY = 'binance_pay_certificates_cache'
    CERTIFICATE_CACHE_TTL = 86400  # 24 hours

    @classmethod
    def get_api_key(cls) -> str:
        key = getattr(settings, 'BINANCE_PAY_CERTIFICATE_SN', '') or getattr(settings, 'BINANCE_PAY_API_KEY', '')
        return key.strip()

    @classmethod
    def get_secret_key(cls) -> str:
        return getattr(settings, 'BINANCE_PAY_SECRET_KEY', '').strip()

    @classmethod
    def get_base_url(cls) -> str:
        return getattr(settings, 'BINANCE_PAY_BASE_URL', 'https://bpay.binanceapi.com').rstrip('/')

    @classmethod
    def is_configured(cls) -> bool:
        api_key = cls.get_api_key()
        secret_key = cls.get_secret_key()
        return bool(api_key and secret_key and not api_key.startswith('mock_'))

    @classmethod
    def _generate_nonce(cls, length: int = 32) -> str:
        """Generates a 32-character random string of ascii letters as required by Binance."""
        return ''.join(secrets.choice(string.ascii_letters) for _ in range(length))

    @classmethod
    def _build_signature(cls, timestamp: str, nonce: str, body_str: str, secret_key: str) -> str:
        """
        Calculates HMAC-SHA512 signature per Binance API specification:
        payload = timestamp + "\\n" + nonce + "\\n" + body + "\\n"
        signature = hex(hmac("sha512", payload, secretKey)).upper()
        """
        payload = f"{timestamp}\n{nonce}\n{body_str}\n"
        return hmac.new(
            secret_key.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha512
        ).hexdigest().upper()

    @classmethod
    def _get_headers(cls, body_str: str) -> Dict[str, str]:
        """Constructs mandatory Binance API request headers."""
        timestamp = str(int(time.time() * 1000))
        nonce = cls._generate_nonce()
        api_key = cls.get_api_key()
        secret_key = cls.get_secret_key()
        signature = cls._build_signature(timestamp, nonce, body_str, secret_key)

        return {
            'Content-Type': 'application/json',
            'BinancePay-Timestamp': timestamp,
            'BinancePay-Nonce': nonce,
            'BinancePay-Certificate-SN': api_key,
            'BinancePay-Signature': signature,
        }

    @classmethod
    def create_order(
        cls,
        merchant_trade_no: str,
        amount: Decimal,
        currency: str = 'USDT',
        goods_name: str = 'Humatron Subscription',
        goods_detail: str = 'Subscription Plan',
        goods_id: str = 'subscription',
        return_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        webhook_url: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Calls Binance Pay Create Order API (POST /binancepay/openapi/v3/order).
        Returns: (success: bool, message: str, data: dict)
        """
        # If credentials are not configured or in test mock mode
        if not cls.is_configured():
            logger.info("Binance Pay running in simulation/mock mode for trade %s", merchant_trade_no)
            mock_expire = int((time.time() + 3600) * 1000)
            mock_data = {
                'prepayId': f"MOCK_PREPAY_{merchant_trade_no}",
                'terminalType': 'WEB',
                'expireTime': mock_expire,
                'qrcodeLink': f"https://mock.binancepay.com/qr/{merchant_trade_no}.png",
                'qrContent': f"binance://pay?prepayId=MOCK_PREPAY_{merchant_trade_no}",
                'checkoutUrl': f"/payments/binance/simulate-checkout/{merchant_trade_no}/",
                'universalUrl': f"https://app.binance.com/qr/dplk#{merchant_trade_no}",
                'deeplink': f"bnc://app.binance.com/payment?prepayId=MOCK_PREPAY_{merchant_trade_no}",
            }
            return True, "Mock order created successfully", mock_data

        url = f"{cls.get_base_url()}/binancepay/openapi/v3/order"
        body = {
            "env": {
                "terminalType": "WEB"
            },
            "merchantTradeNo": str(merchant_trade_no),
            "orderAmount": float(amount),
            "currency": str(currency).upper(),
            "goods": {
                "goodsType": "02",  # 02 = Virtual Goods
                "goodsCategory": "6000",  # Recharge / Virtual service
                "referenceGoodsId": str(goods_id),
                "goodsName": goods_name[:256],
                "goodsDetail": goods_detail[:256]
            }
        }
        if return_url:
            body["returnUrl"] = return_url
        if cancel_url:
            body["cancelUrl"] = cancel_url
        if webhook_url:
            body["webhookUrl"] = webhook_url

        body_str = json.dumps(body, separators=(',', ':'))
        headers = cls._get_headers(body_str)

        try:
            response = requests.post(url, data=body_str, headers=headers, timeout=20)
            res_data = response.json()
            status = res_data.get('status')
            code = res_data.get('code')
            msg = res_data.get('errorMessage') or res_data.get('message') or 'Unknown error'

            if status == 'SUCCESS' and code == '000000':
                return True, "Order created successfully", res_data.get('data', {})

            logger.error("Binance create order failed: [%s] %s | URL: %s", code, msg, url)
            return False, f"Binance error [{code}]: {msg}", None

        except requests.RequestException as e:
            logger.error("Network error communicating with Binance Pay API: %s", e)
            return False, f"Connection error contacting Binance: {str(e)}", None
        except Exception as e:
            logger.error("Unexpected error in Binance create order: %s", e)
            return False, f"Unexpected error: {str(e)}", None

    @classmethod
    def query_order(
        cls,
        merchant_trade_no: Optional[str] = None,
        prepay_id: Optional[str] = None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Calls Binance Pay Query Order API (POST /binancepay/openapi/v2/order/query).
        Returns authoritative server-side status directly from Binance ledger.
        """
        if not merchant_trade_no and not prepay_id:
            return False, "Either merchantTradeNo or prepayId must be provided.", None

        if not cls.is_configured():
            mock_data = {
                'merchantTradeNo': merchant_trade_no or '',
                'prepayId': prepay_id or f"MOCK_PREPAY_{merchant_trade_no}",
                'status': 'PENDING',
                'currency': 'USDT',
                'orderAmount': '50.00',
                'transactionId': f"TX_MOCK_BINANCE_{int(time.time())}",
                'openUserId': 'mock_binance_user',
                'transactTime': int(time.time() * 1000),
            }
            return True, "Mock query verified", mock_data

        url = f"{cls.get_base_url()}/binancepay/openapi/v2/order/query"
        body = {}
        if prepay_id:
            body["prepayId"] = prepay_id
        elif merchant_trade_no:
            body["merchantTradeNo"] = merchant_trade_no

        body_str = json.dumps(body, separators=(',', ':'))
        headers = cls._get_headers(body_str)

        try:
            response = requests.post(url, data=body_str, headers=headers, timeout=15)
            res_data = response.json()
            status = res_data.get('status')
            code = res_data.get('code')
            msg = res_data.get('errorMessage') or res_data.get('message') or 'Query failed'

            if status == 'SUCCESS' and code == '000000':
                return True, "Query successful", res_data.get('data', {})

            logger.warning("Binance query order returned code [%s]: %s", code, msg)
            return False, f"Binance query error [{code}]: {msg}", None

        except requests.RequestException as e:
            logger.error("Connection error querying Binance order: %s", e)
            return False, f"Connection error querying Binance: {str(e)}", None
        except Exception as e:
            logger.error("Unexpected error in query_order: %s", e)
            return False, f"Error querying order: {str(e)}", None

    @classmethod
    def query_certificates(cls, force_refresh: bool = False) -> Dict[str, str]:
        """
        Fetches official Binance Pay public key certificates via POST /binancepay/openapi/certificates.
        Caches certificates in Django cache to prevent redundant external round-trips.
        Returns mapping of: {certSerial: certPublicPEM}
        """
        if not force_refresh:
            cached = cache.get(cls.CERTIFICATE_CACHE_KEY)
            if cached and isinstance(cached, dict):
                return cached

        if not cls.is_configured():
            return {}

        url = f"{cls.get_base_url()}/binancepay/openapi/certificates"
        body_str = "{}"
        headers = cls._get_headers(body_str)

        try:
            response = requests.post(url, data=body_str, headers=headers, timeout=15)
            res_data = response.json()
            if res_data.get('status') == 'SUCCESS' and res_data.get('code') == '000000':
                certs_data = res_data.get('data', [])
                cert_map = {}
                for cert in certs_data:
                    serial = cert.get('certSerial')
                    public_pem = cert.get('certPublic')
                    if serial and public_pem:
                        cert_map[serial] = public_pem

                if cert_map:
                    cache.set(cls.CERTIFICATE_CACHE_KEY, cert_map, timeout=cls.CERTIFICATE_CACHE_TTL)
                return cert_map

            logger.error("Failed to query Binance certificates: %s", res_data)
        except Exception as e:
            logger.error("Exception fetching Binance certificates: %s", e)

        return {}

    @classmethod
    def verify_webhook_signature(
        cls,
        headers: Dict[str, str],
        raw_body_bytes: bytes,
        test_public_key_pem: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Verifies incoming webhook RSA-SHA256 signature according to Binance specification:
        - Header BinancePay-Timestamp
        - Header BinancePay-Nonce
        - Header BinancePay-Certificate-SN
        - Header BinancePay-Signature (Base64 encoded RSA signature)
        - Payload: f"{timestamp}\\n{nonce}\\n{raw_body_str}\\n"
        """
        # Case-insensitive header access
        norm_headers = {k.lower(): v for k, v in headers.items()}
        timestamp = norm_headers.get('binancepay-timestamp')
        nonce = norm_headers.get('binancepay-nonce')
        cert_sn = norm_headers.get('binancepay-certificate-sn')
        signature_b64 = norm_headers.get('binancepay-signature')

        if not timestamp or not nonce or not cert_sn or not signature_b64:
            return False, "Missing mandatory Binance Pay signature headers."

        # Reconstruct signed payload string (LF 0x0A)
        try:
            raw_body_str = raw_body_bytes.decode('utf-8')
        except UnicodeDecodeError:
            return False, "Raw request body must be UTF-8 encoded."

        payload_to_verify = f"{timestamp}\n{nonce}\n{raw_body_str}\n"

        # Resolve public key
        public_pem = test_public_key_pem
        if not public_pem:
            certs = cls.query_certificates(force_refresh=False)
            public_pem = certs.get(cert_sn)
            if not public_pem:
                # Refresh cache once if key not found (possible certificate rotation)
                certs = cls.query_certificates(force_refresh=True)
                public_pem = certs.get(cert_sn)

        if not public_pem:
            # If still not configured and running in test/mock mode
            if not cls.is_configured():
                if signature_b64 == "MOCK_VALID_SIGNATURE":
                    return True, "Mock signature verified."
                return False, "Public key certificate not available for signature verification."
            return False, f"Unknown certificate serial number {cert_sn}."

        try:
            # Decode signature from Base64
            signature_bytes = base64.b64decode(signature_b64)

            # Load RSA public key
            if isinstance(public_pem, str):
                public_pem_bytes = public_pem.encode('utf-8')
            else:
                public_pem_bytes = public_pem

            pub_key = load_pem_public_key(public_pem_bytes)

            # Verify RSA-SHA256 PKCS#1 v1.5
            pub_key.verify(
                signature_bytes,
                payload_to_verify.encode('utf-8'),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            return True, "Signature valid"

        except InvalidSignature:
            logger.warning("Binance webhook RSA signature verification failed.")
            return False, "Invalid signature"
        except Exception as e:
            logger.error("Error during Binance webhook signature verification: %s", e)
            return False, f"Signature verification error: {str(e)}"
