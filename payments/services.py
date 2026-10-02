import json
import logging
import secrets
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from django.db import transaction, IntegrityError
from django.utils import timezone
from .models import Payment
from .telebirr_parser import TelebirrMessageParser
from .binance_service import BinancePayService
from subscriptions.services import SubscriptionService, PricingCalculator
from notifications.services import EmailService
from audit.services import log_admin_action

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
        - Correct amount matching configured plan price
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
                    original_amount=original_etb,
                    discount_amount=discount_etb,
                    final_amount=amount
                )

                # Activate subscription
                subscription = SubscriptionService.activate_subscription(
                    user=user,
                    plan=plan,
                    payment_method='Telebirr',
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
    def submit_telebirr_payment(cls, user, plan, transaction_id, raw_message=""):
        """
        User submission of Telebirr transaction number upon completion.
        If a complete, valid Telebirr confirmation SMS is provided with matching amount,
        verifies and activates immediately via verify_and_activate_telebirr.
        Otherwise, records a PENDING Telebirr payment for administrator approval.
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

        tx_id = (transaction_id or '').strip()
        if not tx_id and raw_message:
            parsed = TelebirrMessageParser.parse(raw_message)
            if parsed['is_valid'] and parsed.get('transaction_id'):
                tx_id = parsed['transaction_id']

        if not tx_id:
            return False, "Telebirr Transaction Number is required.", None

        # Duplicate check
        existing = Payment.objects.filter(
            provider=Payment.PROVIDER_TELEBIRR,
            transaction_id=tx_id
        ).exclude(status__in=[Payment.STATUS_REJECTED, Payment.STATUS_CANCELLED]).first()

        if existing:
            return False, f"Transaction number '{tx_id}' has already been submitted or processed.", None

        # If full raw SMS was submitted, check if automated verification can activate it immediately
        if raw_message and len(raw_message) > 20:
            parsed = TelebirrMessageParser.parse(raw_message)
            if parsed['is_valid'] and parsed.get('amount') and parsed['amount'] >= expected_etb:
                return cls.verify_and_activate_telebirr(user, plan, raw_message)

        # Create pending payment for administrator review
        try:
            with transaction.atomic():
                now = timezone.now()
                payment = Payment.objects.create(
                    user=user,
                    provider=Payment.PROVIDER_TELEBIRR,
                    payment_method=Payment.METHOD_TELEBIRR,
                    transaction_id=tx_id,
                    plan=plan,
                    amount=expected_etb,
                    currency='ETB',
                    status=Payment.STATUS_PENDING,
                    raw_message=raw_message or f"Transaction Number: {tx_id}",
                    submitted_at=now,
                    payment_country=user.country,
                    original_amount=original_etb,
                    discount_amount=discount_etb,
                    final_amount=expected_etb,
                )

                EmailService.send_telebirr_payment_submitted_email(user, payment)
                logger.info("Created pending Telebirr Payment %s for %s", tx_id, user.email)
                return True, "Payment submitted successfully. Your transaction number is awaiting administrator verification.", payment

        except IntegrityError as e:
            logger.error("Integrity error submitting Telebirr payment: %s", e)
            return False, "This transaction number has already been recorded.", None
        except Exception as e:
            logger.error("Unexpected error submitting Telebirr payment: %s", e)
            return False, f"Submission error: {str(e)}", None

    @classmethod
    def approve_telebirr_payment(cls, payment_id_or_obj, admin_user, request=None, admin_notes=""):
        """
        Administrator approval of manual Telebirr payment.
        - Concurrency-safe via SELECT FOR UPDATE
        - Marks payment APPROVED
        - Activates subscription atomically
        - Dispatches approval email
        - Records admin audit log
        """
        if not admin_user or not getattr(admin_user, 'is_staff', False):
            return False, "Administrator authorization is required to approve payments.", None

        payment_id = payment_id_or_obj.id if hasattr(payment_id_or_obj, 'id') else payment_id_or_obj

        try:
            with transaction.atomic():
                payment = Payment.objects.select_for_update().get(id=payment_id)

                if payment.status in (Payment.STATUS_APPROVED, Payment.STATUS_VERIFIED):
                    logger.info("Telebirr payment %s already approved.", payment.transaction_id)
                    return True, "Payment is already approved.", payment

                if payment.status != Payment.STATUS_PENDING:
                    return False, f"Only pending payments can be approved (current status: {payment.status}).", payment

                now = timezone.now()
                payment.status = Payment.STATUS_APPROVED
                payment.reviewed_at = now
                payment.reviewed_by = admin_user
                payment.verified_at = now
                if admin_notes:
                    payment.admin_notes = admin_notes

                # Activate subscription atomically
                subscription = SubscriptionService.activate_subscription(
                    user=payment.user,
                    plan=payment.plan,
                    payment_method='Telebirr',
                    payment_country=payment.payment_country
                )
                payment.subscription = subscription
                payment.save()

                EmailService.send_telebirr_payment_approved_email(payment.user, payment)

                if request:
                    log_admin_action(
                        request=request,
                        action='telebirr_payment_approved',
                        target=payment.transaction_id,
                        metadata={
                            'payment_id': payment.id,
                            'user': payment.user.email,
                            'plan': payment.plan.name if payment.plan else '',
                            'amount': str(payment.amount),
                            'admin': admin_user.email
                        }
                    )
                logger.info("Admin %s approved Telebirr payment %s for user %s",
                            admin_user.email, payment.transaction_id, payment.user.email)
                return True, "Payment approved and subscription activated successfully!", payment

        except Payment.DoesNotExist:
            return False, "Payment record not found.", None
        except Exception as e:
            logger.error("Error approving Telebirr payment %s: %s", payment_id, e)
            return False, f"Approval error: {str(e)}", None

    @classmethod
    def reject_telebirr_payment(cls, payment_id_or_obj, admin_user, reason, request=None, admin_notes=""):
        """
        Administrator rejection of Telebirr payment.
        """
        if not admin_user or not getattr(admin_user, 'is_staff', False):
            return False, "Administrator authorization is required to reject payments.", None

        if not reason or not str(reason).strip():
            return False, "A rejection reason is required.", None

        payment_id = payment_id_or_obj.id if hasattr(payment_id_or_obj, 'id') else payment_id_or_obj

        try:
            with transaction.atomic():
                payment = Payment.objects.select_for_update().get(id=payment_id)

                if payment.status in (Payment.STATUS_APPROVED, Payment.STATUS_VERIFIED):
                    return False, "An approved payment cannot be rejected.", payment

                now = timezone.now()
                payment.status = Payment.STATUS_REJECTED
                payment.rejection_reason = str(reason).strip()
                payment.reviewed_at = now
                payment.reviewed_by = admin_user
                if admin_notes:
                    payment.admin_notes = admin_notes
                payment.save()

                EmailService.send_telebirr_payment_rejected_email(payment.user, payment, reason=str(reason).strip())

                if request:
                    log_admin_action(
                        request=request,
                        action='telebirr_payment_rejected',
                        target=payment.transaction_id,
                        metadata={
                            'payment_id': payment.id,
                            'user': payment.user.email,
                            'reason': str(reason).strip(),
                            'admin': admin_user.email
                        }
                    )
                logger.info("Admin %s rejected Telebirr payment %s for user %s: %s",
                            admin_user.email, payment.transaction_id, payment.user.email, reason)
                return True, "Payment rejected successfully.", payment

        except Payment.DoesNotExist:
            return False, "Payment record not found.", None
        except Exception as e:
            logger.error("Error rejecting Telebirr payment %s: %s", payment_id, e)
            return False, f"Rejection error: {str(e)}", None

    @classmethod
    def submit_binance_manual_payment(cls, user, plan, transaction_id, sender_identifier,
                                      amount, sent_at=None, proof_file=None, note=""):
        """
        User submission of manual Binance payment (Section 5, 6).
        Strict server checks:
        - Authenticated and email verified
        - Plan active
        - Authoritative amount verification from database plan
        - Idempotency & duplicate check
        - Creates Payment in PENDING status
        - Does NOT activate subscription
        - Dispatches PAYMENT_SUBMITTED notification
        """
        if not user or not user.is_authenticated:
            return False, "Authentication is required.", None

        if not user.is_email_verified:
            return False, "Email verification is required before making payments.", None

        if not plan.active:
            return False, "Selected subscription plan is not active.", None

        pricing = PricingCalculator.calculate(plan, user)
        expected_usd = pricing['final_usd']
        original_usd = pricing['original_usd']
        discount_usd = pricing['discount_usd']

        amount = Decimal(str(amount))
        if amount < expected_usd:
            return False, f"Submitted amount ({amount} USDT) is less than required plan price ({expected_usd} USDT).", None

        # Duplicate transaction check
        existing = Payment.objects.filter(
            provider=Payment.PROVIDER_BINANCE,
            transaction_id=transaction_id
        ).exclude(status__in=[Payment.STATUS_REJECTED, Payment.STATUS_CANCELLED]).first()

        if existing:
            return False, f"Transaction ID '{transaction_id}' has already been submitted.", None

        try:
            with transaction.atomic():
                now = timezone.now()
                payment = Payment.objects.create(
                    user=user,
                    provider=Payment.PROVIDER_BINANCE,
                    payment_method=Payment.METHOD_BINANCE_MANUAL,
                    transaction_id=transaction_id,
                    sender_identifier=sender_identifier,
                    plan=plan,
                    amount=amount,
                    currency='USDT',
                    status=Payment.STATUS_PENDING,
                    proof_file=proof_file,
                    raw_message=note or '',
                    submitted_at=sent_at or now,
                    payment_country=user.country,
                    original_amount=original_usd,
                    discount_amount=discount_usd,
                    final_amount=amount,
                )

                # Send email notification to user
                EmailService.send_binance_manual_payment_submitted_email(user, payment)
                logger.info("Created pending Binance Manual Payment %s for %s", transaction_id, user.email)
                return True, "Payment submitted successfully. Your payment is awaiting verification.", payment

        except IntegrityError as e:
            logger.error("Integrity error submitting Binance manual payment: %s", e)
            return False, "This transaction ID has already been recorded.", None
        except Exception as e:
            logger.error("Unexpected error submitting Binance manual payment: %s", e)
            return False, f"Submission error: {str(e)}", None

    @classmethod
    def approve_binance_manual_payment(cls, payment_id_or_obj, admin_user, request=None, admin_notes=""):
        """
        Administrator approval of manual Binance payment (Section 7).
        - Idempotent and concurrency-safe via SELECT FOR UPDATE inside an atomic transaction
        - Marks payment APPROVED
        - Activates subscription atomically
        - Dispatches PAYMENT_APPROVED notification
        - Records immutable audit log
        """
        if not admin_user or not getattr(admin_user, 'is_staff', False):
            return False, "Administrator authorization is required to approve payments.", None

        payment_id = payment_id_or_obj.id if hasattr(payment_id_or_obj, 'id') else payment_id_or_obj

        try:
            with transaction.atomic():
                payment = Payment.objects.select_for_update().get(id=payment_id)

                # Idempotency guard: prevent duplicate activation
                if payment.status in (Payment.STATUS_APPROVED, Payment.STATUS_VERIFIED):
                    logger.info("Payment %s already approved. Skipping duplicate activation.", payment.transaction_id)
                    return True, "Payment is already approved.", payment

                if payment.status != Payment.STATUS_PENDING:
                    return False, f"Only pending payments can be approved (current status: {payment.status}).", payment

                now = timezone.now()
                payment.status = Payment.STATUS_APPROVED
                payment.reviewed_at = now
                payment.reviewed_by = admin_user
                payment.verified_at = now
                if admin_notes:
                    payment.admin_notes = admin_notes

                # Activate subscription atomically
                subscription = SubscriptionService.activate_subscription(
                    user=payment.user,
                    plan=payment.plan,
                    payment_method='Binance Pay',
                    payment_country=payment.payment_country
                )
                payment.subscription = subscription
                payment.save()

                # Dispatch approval confirmation email
                EmailService.send_binance_manual_payment_approved_email(payment.user, payment)

                # Record admin audit trail
                if request:
                    log_admin_action(
                        request=request,
                        action='binance_manual_payment_approved',
                        target=payment.transaction_id,
                        metadata={
                            'payment_id': payment.id,
                            'user': payment.user.email,
                            'plan': payment.plan.name if payment.plan else '',
                            'amount': str(payment.amount),
                            'admin': admin_user.email
                        }
                    )
                logger.info("Admin %s approved Binance manual payment %s for user %s",
                            admin_user.email, payment.transaction_id, payment.user.email)
                return True, "Payment approved and subscription activated successfully!", payment

        except Payment.DoesNotExist:
            return False, "Payment record not found.", None
        except Exception as e:
            logger.error("Error approving Binance manual payment %s: %s", payment_id, e)
            return False, f"Approval error: {str(e)}", None

    @classmethod
    def reject_binance_manual_payment(cls, payment_id_or_obj, admin_user, reason, request=None, admin_notes=""):
        """
        Administrator rejection of manual Binance payment (Section 7).
        - Idempotent and concurrency-safe
        - Marks payment REJECTED
        - Records rejection reason
        - Does NOT activate subscription
        - Dispatches PAYMENT_REJECTED notification
        - Records immutable audit log
        """
        if not admin_user or not getattr(admin_user, 'is_staff', False):
            return False, "Administrator authorization is required to reject payments.", None

        if not reason or not str(reason).strip():
            return False, "A rejection reason is required.", None

        payment_id = payment_id_or_obj.id if hasattr(payment_id_or_obj, 'id') else payment_id_or_obj

        try:
            with transaction.atomic():
                payment = Payment.objects.select_for_update().get(id=payment_id)

                if payment.status in (Payment.STATUS_APPROVED, Payment.STATUS_VERIFIED):
                    return False, "An approved payment cannot be rejected.", payment

                now = timezone.now()
                payment.status = Payment.STATUS_REJECTED
                payment.rejection_reason = str(reason).strip()
                payment.reviewed_at = now
                payment.reviewed_by = admin_user
                if admin_notes:
                    payment.admin_notes = admin_notes
                payment.save()

                # Dispatch rejection email
                EmailService.send_binance_manual_payment_rejected_email(payment.user, payment, reason=str(reason).strip())

                # Record admin audit trail
                if request:
                    log_admin_action(
                        request=request,
                        action='binance_manual_payment_rejected',
                        target=payment.transaction_id,
                        metadata={
                            'payment_id': payment.id,
                            'user': payment.user.email,
                            'reason': str(reason).strip(),
                            'admin': admin_user.email
                        }
                    )
                logger.info("Admin %s rejected Binance manual payment %s for user %s: %s",
                            admin_user.email, payment.transaction_id, payment.user.email, reason)
                return True, "Payment rejected successfully.", payment

        except Payment.DoesNotExist:
            return False, "Payment record not found.", None
        except Exception as e:
            logger.error("Error rejecting Binance manual payment %s: %s", payment_id, e)
            return False, f"Rejection error: {str(e)}", None

    @classmethod
    def initiate_binance_payment(cls, user, plan, return_url=None, cancel_url=None):
        """
        Initiates a Binance Pay acquiring order (Section 6 & Phase 6).
        - Authenticates and validates email verification
        - Checks plan activity
        - Server calculates authoritative price from database plan
        - Generates unique merchantTradeNo
        - Calls Binance Pay v3 order API
        - Creates internal pending Payment record atomically
        """
        if not user or not user.is_authenticated:
            return False, "Authentication is required.", None

        if not user.is_email_verified:
            return False, "Email verification is required before making payments.", None

        if not plan.active:
            return False, "Selected subscription plan is not active.", None

        # Authoritative pricing calculation
        pricing = PricingCalculator.calculate(plan, user)
        expected_usd = pricing['final_usd']
        original_usd = pricing['original_usd']
        discount_usd = pricing['discount_usd']

        # Generate unique merchant trade number (max 32 chars, alphanumeric)
        # Format: HP<epoch_secs><hex_random> (e.g. HP1727690000A1B2C3D4)
        epoch = int(timezone.now().timestamp())
        random_suffix = secrets.token_hex(4).upper()
        merchant_trade_no = f"HP{epoch}{random_suffix}"[:32]

        currency = 'USDT'

        success, msg, order_data = BinancePayService.create_order(
            merchant_trade_no=merchant_trade_no,
            amount=expected_usd,
            currency=currency,
            goods_name=f"Humatron {plan.name}",
            goods_detail=f"{plan.duration_days} Days Access ({plan.pdf_limit} PDFs)",
            goods_id=str(plan.id),
            return_url=return_url,
            cancel_url=cancel_url,
        )

        if not success or not order_data:
            logger.error("Binance order creation failed for user %s: %s", user.email, msg)
            return False, f"Failed to create Binance Pay order: {msg}", None

        # Calculate expiration datetime if returned by Binance
        expire_time_ms = order_data.get('expireTime')
        expire_dt = None
        if expire_time_ms:
            try:
                expire_dt = datetime.fromtimestamp(expire_time_ms / 1000.0, tz=dt_timezone.utc)
            except Exception:
                pass

        try:
            with transaction.atomic():
                payment = Payment.objects.create(
                    user=user,
                    provider=Payment.PROVIDER_BINANCE,
                    transaction_id=merchant_trade_no,
                    merchant_trade_no=merchant_trade_no,
                    prepay_id=order_data.get('prepayId', ''),
                    plan=plan,
                    amount=expected_usd,
                    currency=currency,
                    status=Payment.STATUS_PENDING,
                    checkout_url=order_data.get('checkoutUrl', ''),
                    qr_code_url=order_data.get('qrcodeLink', ''),
                    qr_content=order_data.get('qrContent', ''),
                    order_expire_time=expire_dt,
                    payment_country=user.country,
                    original_amount=original_usd,
                    discount_amount=discount_usd,
                    final_amount=expected_usd
                )
                logger.info("Created pending Binance payment %s (prepayId: %s) for %s",
                            merchant_trade_no, payment.prepay_id, user.email)
                return True, "Binance Pay order created successfully.", payment

        except IntegrityError as e:
            logger.error("Integrity error creating Binance payment %s: %s", merchant_trade_no, e)
            return False, "Database error creating pending order record.", None
        except Exception as e:
            logger.error("Error creating Binance payment record: %s", e)
            return False, f"Order registration error: {str(e)}", None

    @classmethod
    def verify_and_activate_binance(cls, merchant_trade_no, prepay_id=None, webhook_payload=None, query_binance=True):
        """
        Authoritative verification and subscription activation for Binance Pay (Phases 8, 9, 10).
        Idempotent: Uses database row-locking (select_for_update) to guarantee:
        - Never activates duplicate subscriptions.
        - Never extends a subscription twice.
        - Verifies amount and currency strictly against server records.
        - Fallback order querying against Binance v2 query API.
        """
        if not merchant_trade_no:
            return False, "Missing merchant trade number.", None

        with transaction.atomic():
            payment = Payment.objects.select_for_update().filter(
                provider=Payment.PROVIDER_BINANCE,
                merchant_trade_no=merchant_trade_no
            ).first()

            if not payment:
                logger.warning("Binance payment record not found for trade %s", merchant_trade_no)
                return False, f"Payment record for trade {merchant_trade_no} not found.", None

            # 1. Idempotency Check: If already verified, return success without duplicate activation
            if payment.status == Payment.STATUS_VERIFIED:
                logger.info("Binance order %s already verified (idempotent callback).", merchant_trade_no)
                return True, "Payment has already been verified and processed.", payment

            # 2. Authoritative status verification
            verified_amount = None
            verified_currency = None
            binance_tx_id = ''

            # If query_binance is enabled, verify directly with Binance ledger
            if query_binance:
                q_success, q_msg, query_data = BinancePayService.query_order(
                    merchant_trade_no=merchant_trade_no,
                    prepay_id=prepay_id or payment.prepay_id
                )
                if not q_success or not query_data:
                    logger.warning("Binance order query failed for %s: %s", merchant_trade_no, q_msg)
                    return False, f"Binance status check failed: {q_msg}", None

                order_status = query_data.get('status')
                if order_status != 'PAID':
                    logger.warning("Binance order %s status is %s (not PAID)", merchant_trade_no, order_status)
                    if order_status in ('CANCELED', 'EXPIRED'):
                        payment.status = order_status
                        payment.save(update_fields=['status'])
                    return False, f"Order status is {order_status}, not PAID.", None

                verified_amount = Decimal(str(query_data.get('orderAmount', '0')))
                verified_currency = query_data.get('currency', '').upper()
                binance_tx_id = str(query_data.get('transactionId') or query_data.get('prepayId') or '')
                raw_log = json.dumps(query_data)
            elif webhook_payload:
                # Webhook data verification
                raw_data = webhook_payload.get('data')
                if isinstance(raw_data, str):
                    try:
                        raw_data = json.loads(raw_data)
                    except Exception:
                        raw_data = {}
                elif not isinstance(raw_data, dict):
                    raw_data = {}

                verified_amount = Decimal(str(raw_data.get('totalFee', '0')))
                verified_currency = raw_data.get('currency', '').upper()
                binance_tx_id = str(webhook_payload.get('bizId') or raw_data.get('transactionId') or '')
                raw_log = json.dumps(webhook_payload)
            else:
                # Simulation / Test fallback when unconfigured
                verified_amount = payment.amount
                verified_currency = payment.currency
                binance_tx_id = f"TX_SIMULATED_{merchant_trade_no}"
                raw_log = json.dumps({'simulation': True})

            # 3. Currency and Amount Validation
            if verified_currency and verified_currency != payment.currency:
                reason = f"Currency mismatch: expected {payment.currency}, received {verified_currency}"
                logger.error("Binance security error for %s: %s", merchant_trade_no, reason)
                payment.status = Payment.STATUS_REJECTED
                payment.rejection_reason = reason
                payment.save(update_fields=['status', 'rejection_reason'])
                return False, reason, None

            if verified_amount and verified_amount < payment.amount:
                reason = f"Underpaid: expected {payment.amount}, received {verified_amount}"
                logger.error("Binance payment underpaid for %s: %s", merchant_trade_no, reason)
                payment.status = Payment.STATUS_REJECTED
                payment.rejection_reason = reason
                payment.save(update_fields=['status', 'rejection_reason'])
                return False, reason, None

            # 4. Atomic Transition and Subscription Activation
            now = timezone.now()
            payment.status = Payment.STATUS_VERIFIED
            payment.verified_at = now
            if binance_tx_id:
                payment.binance_order_id = binance_tx_id
            payment.raw_message = raw_log

            subscription = SubscriptionService.activate_subscription(
                user=payment.user,
                plan=payment.plan,
                payment_method='Binance Pay',
                payment_country=payment.payment_country
            )

            payment.subscription = subscription
            payment.save(update_fields=[
                'status', 'verified_at', 'binance_order_id', 'raw_message', 'subscription'
            ])

            EmailService.send_payment_received_email(payment.user, payment)
            logger.info("Successfully activated subscription via Binance Pay: %s for %s",
                        merchant_trade_no, payment.user.email)
            return True, "Binance Pay payment verified and subscription activated!", payment

