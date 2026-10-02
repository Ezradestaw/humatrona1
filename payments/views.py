import json
import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from django.http import JsonResponse, HttpResponseForbidden, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from .forms import TelebirrVerificationForm, BinanceManualSubmissionForm
from .models import Payment, BinanceManualPaymentSettings, TelebirrPaymentSettings
from .services import PaymentService
from .binance_service import BinancePayService
from subscriptions.models import SubscriptionPlan
from subscriptions.services import PricingCalculator

logger = logging.getLogger('humatron')


@login_required
def checkout_view(request, plan_code):
    plan = SubscriptionPlan.objects.filter(active=True).filter(
        models.Q(slug=plan_code) | models.Q(code=plan_code)
    ).first()
    if not plan:
        raise Http404("Subscription plan not found.")

    user = request.user

    # Free plan instant activation without payment
    if plan.price == 0 or getattr(plan, 'slug', '') == 'free':
        from subscriptions.services import SubscriptionService
        SubscriptionService.activate_subscription(
            user=user,
            plan=plan,
            payment_method='FREE'
        )
        messages.success(request, f"Your Free plan ({plan.usage_limit} PDFs/month) has been activated successfully!")
        return redirect('accounts:dashboard')

    # Server determines country from authenticated user record
    is_ethiopia = (user.country.strip().lower() == 'ethiopia')
    pricing = PricingCalculator.calculate(plan, user)
    manual_settings = BinanceManualPaymentSettings.get_settings()
    telebirr_settings = TelebirrPaymentSettings.get_settings()

    context = {
        'plan': plan,
        'pricing': pricing,
        'is_ethiopia': is_ethiopia,
        'telebirr_settings': telebirr_settings,
        'telebirr_phone': telebirr_settings.phone_number,
        'telebirr_merchant': telebirr_settings.receiver_name,
        'manual_settings': manual_settings,
        'binance_manual_enabled': manual_settings.enabled,
        'form': TelebirrVerificationForm(),
    }
    return render(request, 'payments/checkout.html', context)


@login_required
def verify_telebirr_view(request, plan_code):
    # Strict server verification of country: Section 5
    if request.user.country.strip().lower() != 'ethiopia':
        return HttpResponseForbidden("Telebirr verification is only available for accounts registered in Ethiopia.")

    plan = SubscriptionPlan.objects.filter(active=True).filter(
        models.Q(slug=plan_code) | models.Q(code=plan_code)
    ).first()
    if not plan:
        raise Http404("Subscription plan not found.")

    telebirr_settings = TelebirrPaymentSettings.get_settings()

    if request.method == 'POST':
        form = TelebirrVerificationForm(request.POST)
        if form.is_valid():
            tx_id = form.cleaned_data.get('transaction_id', '').strip()
            raw_message = form.cleaned_data.get('raw_message', '').strip()

            # If full SMS message was provided, attempt direct automated verification
            if raw_message and len(raw_message) > 20:
                success, msg, payment = PaymentService.verify_and_activate_telebirr(
                    user=request.user,
                    plan=plan,
                    raw_message=raw_message
                )
            else:
                # Customer uploaded/entered their transaction number upon completion
                success, msg, payment = PaymentService.submit_telebirr_payment(
                    user=request.user,
                    plan=plan,
                    transaction_id=tx_id,
                    raw_message=raw_message
                )

            if success:
                messages.success(request, msg)
                return redirect('accounts:dashboard')
            else:
                messages.error(request, msg)
    else:
        form = TelebirrVerificationForm()

    pricing = PricingCalculator.calculate(plan, request.user)
    return render(request, 'payments/telebirr_verify.html', {
        'plan': plan,
        'pricing': pricing,
        'form': form,
        'telebirr_settings': telebirr_settings,
        'telebirr_phone': telebirr_settings.phone_number,
        'telebirr_merchant': telebirr_settings.receiver_name,
    })


@login_required
def payment_history_view(request):
    """
    Section 37: User sees their own payment history.
    Strict object authorization: only request.user's payments are returned.
    """
    payments = Payment.objects.filter(user=request.user).order_by('-received_at')
    return render(request, 'payments/history.html', {'payments': payments})


@login_required
def binance_manual_checkout_view(request, plan_code):
    """
    Binance Payment checkout page and submission handler (Section 2, 5).
    Displays admin-configured receiving identifier, QR code, and clear instructions.
    Accepts customer submission of TxID, sender UID, proof screenshot, and notes.
    """
    plan = SubscriptionPlan.objects.filter(active=True).filter(
        models.Q(slug=plan_code) | models.Q(code=plan_code)
    ).first()
    if not plan:
        raise Http404("Subscription plan not found.")

    user = request.user
    if plan.price == 0 or getattr(plan, 'slug', '') == 'free':
        return redirect('payments:checkout', plan_code=plan.slug or plan.code)

    pricing = PricingCalculator.calculate(plan, user)
    manual_settings = BinanceManualPaymentSettings.get_settings()
    expected_amount = pricing['final_usd']

    if request.method == 'POST':
        form = BinanceManualSubmissionForm(
            request.POST,
            request.FILES,
            expected_amount=expected_amount,
            user=user
        )
        if form.is_valid():
            success, msg, payment = PaymentService.submit_binance_manual_payment(
                user=user,
                plan=plan,
                transaction_id=form.cleaned_data['transaction_id'],
                sender_identifier=form.cleaned_data['sender_identifier'],
                amount=form.cleaned_data['amount'],
                sent_at=form.cleaned_data.get('sent_at'),
                proof_file=form.cleaned_data.get('proof_file'),
                note=form.cleaned_data.get('note', '')
            )
            if success and payment:
                messages.success(request, msg)
                return redirect('payments:binance_manual_status', payment_id=payment.id)
            else:
                messages.error(request, msg)
    else:
        form = BinanceManualSubmissionForm(expected_amount=expected_amount, user=user)

    context = {
        'plan': plan,
        'pricing': pricing,
        'manual_settings': manual_settings,
        'expected_amount': expected_amount,
        'form': form,
    }
    return render(request, 'payments/binance_manual_checkout.html', context)


@login_required
def binance_manual_status_view(request, payment_id):
    """
    User-facing payment status page (Section 8).
    Strict authorization: user can only view their own payment submission.
    """
    payment = get_object_or_404(Payment, id=payment_id, user=request.user)
    manual_settings = BinanceManualPaymentSettings.get_settings()

    context = {
        'payment': payment,
        'plan': payment.plan,
        'subscription': payment.subscription,
        'manual_settings': manual_settings,
    }
    return render(request, 'payments/binance_manual_status.html', context)


@csrf_exempt
def telebirr_webhook_view(request):
    """
    Section 28: Authorized automated message receiver.
    Accepts incoming SMS notifications from authorized forwarders.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body.decode('utf-8'))
        raw_message = data.get('message', '')
        user_email = data.get('user_email')
        plan_code = data.get('plan_code', 'professional')

        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.filter(email=user_email).first()
        plan = SubscriptionPlan.objects.filter(code=plan_code, active=True).first()

        if not user or not plan:
            return JsonResponse({'error': 'User or plan not found'}, status=404)

        success, msg, payment = PaymentService.verify_and_activate_telebirr(user, plan, raw_message)
        return JsonResponse({'success': success, 'message': msg})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
def initiate_binance_pay_view(request, plan_code):
    """
    Initiates Binance Pay order for the requested subscription plan (Phase 6).
    Returns JSON checkout metadata or redirects to the Binance Pay checkout URL.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)

    plan = get_object_or_404(SubscriptionPlan, code=plan_code, active=True)
    return_url = getattr(settings, 'BINANCE_PAY_RETURN_URL', '')
    if not return_url:
        return_url = request.build_absolute_uri('/payments/binance/return/')

    cancel_url = getattr(settings, 'BINANCE_PAY_CANCEL_URL', '')
    if not cancel_url:
        cancel_url = request.build_absolute_uri('/payments/binance/cancel/')

    success, msg, payment = PaymentService.initiate_binance_payment(
        user=request.user,
        plan=plan,
        return_url=return_url,
        cancel_url=cancel_url,
    )

    if not success or not payment:
        logger.error("Failed to initiate Binance Pay: %s", msg)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', ''):
            return JsonResponse({'success': False, 'message': msg}, status=400)
        messages.error(request, msg)
        return redirect('payments:checkout', plan_code=plan.code)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', ''):
        return JsonResponse({
            'success': True,
            'merchant_trade_no': payment.merchant_trade_no,
            'checkout_url': payment.checkout_url,
            'qr_code_url': payment.qr_code_url,
            'qr_content': payment.qr_content,
            'prepay_id': payment.prepay_id,
            'amount': str(payment.amount),
            'currency': payment.currency,
        })

    return redirect(payment.checkout_url)


@login_required
def binance_return_view(request):
    """
    Handles customer returning from Binance hosted checkout (Phase 7, 9).
    Never assumes browser arrival indicates payment; checks authoritative server status.
    """
    merchant_trade_no = request.GET.get('merchantTradeNo') or request.GET.get('tradeNo')
    payment = None
    if merchant_trade_no:
        payment = Payment.objects.filter(
            provider=Payment.PROVIDER_BINANCE,
            merchant_trade_no=merchant_trade_no,
            user=request.user
        ).first()

    if not payment:
        payment = Payment.objects.filter(
            provider=Payment.PROVIDER_BINANCE,
            user=request.user
        ).order_by('-received_at').first()

    if not payment:
        messages.error(request, "No Binance payment order found.")
        return redirect('subscriptions:plans')

    if payment.status == Payment.STATUS_VERIFIED:
        messages.success(request, f"Your payment has been confirmed and your {payment.plan.name} subscription is active!")
        return redirect('accounts:dashboard')

    # Query Binance fallback check
    PaymentService.verify_and_activate_binance(payment.merchant_trade_no, query_binance=True)
    payment.refresh_from_db()

    if payment.status == Payment.STATUS_VERIFIED:
        messages.success(request, f"Your payment has been confirmed and your {payment.plan.name} subscription is active!")
        return redirect('accounts:dashboard')

    return render(request, 'payments/binance_return.html', {
        'payment': payment,
        'merchant_trade_no': payment.merchant_trade_no,
    })


@login_required
def binance_cancel_view(request):
    """Handles cancellation when user abandons or cancels payment on Binance."""
    merchant_trade_no = request.GET.get('merchantTradeNo')
    if merchant_trade_no:
        payment = Payment.objects.filter(
            provider=Payment.PROVIDER_BINANCE,
            merchant_trade_no=merchant_trade_no,
            user=request.user
        ).first()
        if payment and payment.status == Payment.STATUS_PENDING:
            payment.status = Payment.STATUS_CANCELLED
            payment.save(update_fields=['status'])

    messages.info(request, "Binance Pay checkout was cancelled.")
    return redirect('subscriptions:plans')


@login_required
def binance_order_status_api(request, merchant_trade_no):
    """
    API endpoint for frontend status polling (Phase 7).
    Guarantees user object authorization: user can only poll their own order.
    """
    payment = get_object_or_404(
        Payment,
        provider=Payment.PROVIDER_BINANCE,
        merchant_trade_no=merchant_trade_no,
        user=request.user
    )

    if payment.status == Payment.STATUS_PENDING:
        PaymentService.verify_and_activate_binance(payment.merchant_trade_no, query_binance=True)
        payment.refresh_from_db()

    return JsonResponse({
        'merchant_trade_no': payment.merchant_trade_no,
        'status': payment.status,
        'is_verified': (payment.status == Payment.STATUS_VERIFIED),
        'plan_name': payment.plan.name if payment.plan else '',
        'redirect_url': '/dashboard/' if payment.status == Payment.STATUS_VERIFIED else None,
    })


@csrf_exempt
def binance_webhook_view(request):
    """
    Official Binance Pay Webhook Notification receiver (Phase 8).
    Strictly verifies RSA-SHA256 signature using Binance public certificate.
    Processes idempotently with database row locking.
    Returns HTTP 200 {"returnCode": "SUCCESS", "returnMessage": null}
    """
    if request.method != 'POST':
        return JsonResponse({'returnCode': 'FAIL', 'returnMessage': 'Method not allowed'}, status=405)

    headers = {k: v for k, v in request.headers.items()}
    raw_body = request.body

    # 1. Verify RSA signature
    is_valid, reason = BinancePayService.verify_webhook_signature(headers, raw_body)
    if not is_valid:
        logger.warning("Rejected Binance webhook with invalid signature: %s", reason)
        return JsonResponse({'returnCode': 'FAIL', 'returnMessage': reason}, status=400)

    # 2. Parse payload safely
    try:
        payload = json.loads(raw_body.decode('utf-8'))
    except Exception as e:
        logger.error("Failed to parse Binance webhook JSON: %s", e)
        return JsonResponse({'returnCode': 'FAIL', 'returnMessage': 'Invalid JSON body'}, status=400)

    biz_type = payload.get('bizType')
    biz_status = payload.get('bizStatus')
    data = payload.get('data')

    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = {}
    elif not isinstance(data, dict):
        data = {}

    merchant_trade_no = data.get('merchantTradeNo')
    prepay_id = str(payload.get('bizId') or data.get('prepayId') or '')

    logger.info("Received Binance webhook: bizType=%s bizStatus=%s trade=%s",
                biz_type, biz_status, merchant_trade_no)

    if biz_status == 'PAY_SUCCESS':
        success, msg, payment = PaymentService.verify_and_activate_binance(
            merchant_trade_no=merchant_trade_no,
            prepay_id=prepay_id,
            webhook_payload=payload,
            query_binance=False
        )
        if not success:
            logger.warning("Failed to process PAY_SUCCESS webhook for trade %s: %s", merchant_trade_no, msg)

    elif biz_status in ('PAY_CLOSED', 'PAY_EXPIRED'):
        payment = Payment.objects.filter(
            provider=Payment.PROVIDER_BINANCE,
            merchant_trade_no=merchant_trade_no
        ).first()
        if payment and payment.status == Payment.STATUS_PENDING:
            payment.status = Payment.STATUS_CANCELLED if biz_status == 'PAY_CLOSED' else Payment.STATUS_EXPIRED
            payment.save(update_fields=['status'])
            logger.info("Updated Binance payment %s to status %s", merchant_trade_no, payment.status)

    return JsonResponse({'returnCode': 'SUCCESS', 'returnMessage': None}, status=200)


@login_required
def binance_simulate_checkout_view(request, merchant_trade_no):
    """
    Local simulation checkout helper for testing without live Binance keys.
    """
    payment = get_object_or_404(
        Payment,
        provider=Payment.PROVIDER_BINANCE,
        merchant_trade_no=merchant_trade_no,
        user=request.user
    )

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'confirm':
            PaymentService.verify_and_activate_binance(
                merchant_trade_no=merchant_trade_no,
                query_binance=False
            )
            messages.success(request, "Simulated Binance payment completed successfully!")
            return redirect('accounts:dashboard')
        elif action == 'cancel':
            payment.status = Payment.STATUS_CANCELLED
            payment.save(update_fields=['status'])
            messages.info(request, "Simulated payment cancelled.")
            return redirect('subscriptions:plans')

    return render(request, 'payments/binance_simulate.html', {'payment': payment})
