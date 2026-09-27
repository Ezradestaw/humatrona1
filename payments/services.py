import logging
from decimal import Decimal
from django.db import transaction, IntegrityError
from django.utils import timezone
from .models import Payment
from .telebirr_parser import TelebirrMessageParser
from .paypal_service import PayPalService
from subscriptions.services import SubscriptionService
from notifications.services import EmailService

logger = logging.getLogger('humatron')


class PaymentProcessingError(Exception):
    pass


class PaymentService:
    """
    Authoritative server-side payment verification and subscription activation engine.
    Guarantees idempotency, atomic rollbacks, and strict amount verification (Sections 27-32).
    """

    @classmethod
    def verify_and_activate_telebirr(cls, user, plan, raw_message):
        """
        Parses and verifies a Telebirr payment message and activates subscription atomically.
        """
        parsed = TelebirrMessageParser.parse(raw_message)
        if not parsed['is_valid']:
            err_msg = "; ".join(parsed['errors'])
            logger.warning("Invalid Telebirr message submitted by %s: %s", user.email, err_msg)
            return False, f"Message parsing error: {err_msg}", None

        tx_id = parsed['transaction_id']
        amount = parsed['amount']
        currency = parsed['currency']

        # 1. Uniqueness check (Idempotency & Duplicate Protection - Sec 30)
        existing = Payment.objects.filter(provider=Payment.PROVIDER_TELEBIRR, transaction_id=tx_id).first()
        if existing:
            logger.warning("Duplicate Telebirr transaction submitted: %s by %s", tx_id, user.email)
            return False, f"Transaction {tx_id} has already been processed and cannot be reused.", None

        # 2. Amount verification against plan ETB price (Sec 31)
        expected_etb = plan.price_etb
        if amount < expected_etb:
            # Record rejected attempt for audit trail
            Payment.objects.create(
                user=user,
                provider=Payment.PROVIDER_TELEBIRR,
                transaction_id=tx_id,
                plan=plan,
                amount=amount,
                currency=currency,
                status=Payment.STATUS_REJECTED,
                raw_message=raw_message,
                message_hash=parsed['message_hash'],
                rejection_reason=f"Insufficient amount. Required: {expected_etb} ETB, Provided: {amount} ETB."
            )
            reason = f"Payment of {amount} ETB is less than the plan price of {expected_etb} ETB."
            logger.warning("Underpaid Telebirr transaction: %s", reason)
            return False, reason, None

        # 3. Atomic Database Transaction (Section 32)
        try:
            with transaction.atomic():
                now = timezone.now()
                payment = Payment.objects.create(
                    user=user,
                    provider=Payment.PROVIDER_TELEBIRR,
                    transaction_id=tx_id,
                    plan=plan,
                    amount=amount,
                    currency=currency,
                    status=Payment.STATUS_VERIFIED,
                    raw_message=raw_message,
                    message_hash=parsed['message_hash'],
                    merchant_account=parsed.get('phone_found') or '',
                    verified_at=now
                )

                # Activate subscription
                subscription = SubscriptionService.activate_subscription(
                    user=user,
                    plan=plan,
                    payment_method='Telebirr'
                )

                payment.subscription = subscription
                payment.save(update_fields=['subscription'])

                # Send notifications
                EmailService.send_payment_received_email(user, payment)
                logger.info("Successfully activated subscription via Telebirr: %s for %s", tx_id, user.email)
                return True, "Payment verified and subscription activated successfully!", payment

        except IntegrityError as e:
            logger.error("Database integrity error activating Telebirr: %s", e)
            return False, "This transaction has already been registered in the system.", None
        except Exception as e:
            logger.error("Unexpected error activating Telebirr: %s", e)
            return False, f"Activation error: {str(e)}", None

    @classmethod
    def verify_and_activate_paypal(cls, user, plan, order_id):
        """
        Verifies captured PayPal order and activates subscription atomically.
        """
        # 1. Uniqueness check (Sec 27 idempotency)
        existing = Payment.objects.filter(provider=Payment.PROVIDER_PAYPAL, transaction_id=order_id).first()
        if existing:
            return False, f"PayPal order {order_id} has already been processed.", None

        # 2. Server-side API verification with PayPal
        verified, message, capture_data = PayPalService.verify_and_capture_order(
            order_id=order_id,
            expected_amount=plan.price,
            expected_currency=plan.currency
        )
        if not verified:
            logger.warning("PayPal verification failed for %s: %s", order_id, message)
            return False, f"PayPal verification failed: {message}", None

        # 3. Atomic Database Transaction (Section 32)
        try:
            with transaction.atomic():
                now = timezone.now()
                payment = Payment.objects.create(
                    user=user,
                    provider=Payment.PROVIDER_PAYPAL,
                    transaction_id=order_id,
                    plan=plan,
                    amount=plan.price,
                    currency=plan.currency,
                    status=Payment.STATUS_VERIFIED,
                    raw_message=str(capture_data),
                    verified_at=now
                )

                subscription = SubscriptionService.activate_subscription(
                    user=user,
                    plan=plan,
                    payment_method='PayPal'
                )

                payment.subscription = subscription
                payment.save(update_fields=['subscription'])

                EmailService.send_payment_received_email(user, payment)
                logger.info("Successfully activated subscription via PayPal: %s for %s", order_id, user.email)
                return True, "PayPal payment verified and subscription activated!", payment

        except IntegrityError:
            return False, "This PayPal transaction has already been registered.", None
        except Exception as e:
            logger.error("Error activating PayPal: %s", e)
            return False, f"Activation error: {str(e)}", None
