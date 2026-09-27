import logging
from decimal import Decimal
from django.db import transaction, IntegrityError
from django.utils import timezone
from .models import Payment
from .telebirr_parser import TelebirrMessageParser
from .paypal_service import PayPalService
from subscriptions.services import SubscriptionService, PricingCalculator
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
        Strict server checks:
        - Authenticated and email verified
        - User registered country must be Ethiopia
        - Plan active and has configured ETB price
        - Transaction not used (idempotency)
        - Correct amount (with 25% student discount if verified)
        """
        if not user or not user.is_authenticated:
            return False, "Authentication is required.", None

        if not user.is_email_verified:
            return False, "Email verification is required before making payments.", None

        if user.country.strip().lower() != 'ethiopia':
            return False, "Telebirr payment is only permitted for verified accounts registered in Ethiopia.", None

        if not plan.active:
            return False, "Selected subscription plan is not active.", None

        pricing = PricingCalculator.calculate(plan, user)
        if not pricing['has_configured_etb'] or pricing['final_etb'] is None:
            return False, "This plan does not have an Ethiopian payment amount configured by an administrator.", None

        expected_etb = pricing['final_etb']
        original_etb = pricing['original_etb']
        discount_etb = pricing['discount_etb']
        is_student = pricing['is_student_discount']
        discount_pct = pricing['discount_percentage']

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

        # 2. Amount verification against calculated plan ETB price (Sec 31)
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
                rejection_reason=f"Insufficient amount. Required: {expected_etb} ETB, Provided: {amount} ETB.",
                payment_country=user.country,
                student_discount_applied=is_student,
                discount_percentage=discount_pct,
                original_amount=original_etb,
                discount_amount=discount_etb,
                final_amount=amount
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
                    verified_at=now,
                    payment_country=user.country,
                    student_discount_applied=is_student,
                    discount_percentage=discount_pct,
                    original_amount=original_etb,
                    discount_amount=discount_etb,
                    final_amount=amount
                )

                # Activate subscription
                subscription = SubscriptionService.activate_subscription(
                    user=user,
                    plan=plan,
                    payment_method='Telebirr',
                    student_discount_applied=is_student,
                    discount_percentage=discount_pct,
                    payment_country=user.country
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
        Calculates authoritative discounted price for verified students.
        """
        if not user or not user.is_authenticated:
            return False, "Authentication is required.", None

        if not user.is_email_verified:
            return False, "Email verification is required before making payments.", None

        if not plan.active:
            return False, "Selected subscription plan is not active.", None

        # 1. Uniqueness check (Sec 27 idempotency)
        existing = Payment.objects.filter(provider=Payment.PROVIDER_PAYPAL, transaction_id=order_id).first()
        if existing:
            return False, f"PayPal order {order_id} has already been processed.", None

        # Calculate expected price (with student discount if verified)
        pricing = PricingCalculator.calculate(plan, user)
        expected_usd = pricing['final_usd']
        original_usd = pricing['original_usd']
        discount_usd = pricing['discount_usd']
        is_student = pricing['is_student_discount']
        discount_pct = pricing['discount_percentage']

        # 2. Server-side API verification with PayPal
        verified, message, capture_data = PayPalService.verify_and_capture_order(
            order_id=order_id,
            expected_amount=expected_usd,
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
                    amount=expected_usd,
                    currency=plan.currency,
                    status=Payment.STATUS_VERIFIED,
                    raw_message=str(capture_data),
                    verified_at=now,
                    payment_country=user.country,
                    student_discount_applied=is_student,
                    discount_percentage=discount_pct,
                    original_amount=original_usd,
                    discount_amount=discount_usd,
                    final_amount=expected_usd
                )

                subscription = SubscriptionService.activate_subscription(
                    user=user,
                    plan=plan,
                    payment_method='PayPal',
                    student_discount_applied=is_student,
                    discount_percentage=discount_pct,
                    payment_country=user.country
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

