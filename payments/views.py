import json
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from .forms import TelebirrVerificationForm
from .models import Payment
from .services import PaymentService
from subscriptions.models import SubscriptionPlan
from subscriptions.services import PricingCalculator


@login_required
def checkout_view(request, plan_code):
    plan = get_object_or_404(SubscriptionPlan, code=plan_code, active=True)
    user = request.user

    # Server determines country from authenticated user record
    is_ethiopia = (user.country.strip().lower() == 'ethiopia')
    pricing = PricingCalculator.calculate(plan, user)

    context = {
        'plan': plan,
        'pricing': pricing,
        'is_ethiopia': is_ethiopia,
        'telebirr_phone': getattr(settings, 'TELEBIRR_RECEIVER_PHONE', '0911000000'),
        'telebirr_merchant': getattr(settings, 'TELEBIRR_MERCHANT_NAME', 'Humatron Technologies'),
        'paypal_client_id': getattr(settings, 'PAYPAL_CLIENT_ID', ''),
        'form': TelebirrVerificationForm(),
    }
    return render(request, 'payments/checkout.html', context)


@login_required
def verify_telebirr_view(request, plan_code):
    # Strict server verification of country: Section 5
    if request.user.country.strip().lower() != 'ethiopia':
        return HttpResponseForbidden("Telebirr verification is only available for accounts registered in Ethiopia.")

    plan = get_object_or_404(SubscriptionPlan, code=plan_code, active=True)
    if request.method == 'POST':
        form = TelebirrVerificationForm(request.POST)
        if form.is_valid():
            raw_message = form.cleaned_data['raw_message']
            success, msg, payment = PaymentService.verify_and_activate_telebirr(
                user=request.user,
                plan=plan,
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
    return render(request, 'payments/telebirr_verify.html', {'plan': plan, 'pricing': pricing, 'form': form})


@login_required
def capture_paypal_view(request, plan_code):
    plan = get_object_or_404(SubscriptionPlan, code=plan_code, active=True)
    if request.method == 'POST':
        order_id = request.POST.get('order_id')
        if not order_id:
            try:
                body = json.loads(request.body.decode('utf-8'))
                order_id = body.get('order_id')
            except Exception:
                pass

        if not order_id:
            return JsonResponse({'success': False, 'message': 'Missing PayPal Order ID.'}, status=400)

        success, msg, payment = PaymentService.verify_and_activate_paypal(
            user=request.user,
            plan=plan,
            order_id=order_id
        )
        if success:
            messages.success(request, "PayPal payment verified! Your subscription is now active.")
            return JsonResponse({'success': True, 'redirect_url': '/dashboard/'})
        else:
            return JsonResponse({'success': False, 'message': msg}, status=400)

    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
def payment_history_view(request):
    """
    Section 37: User sees their own payment history.
    Strict object authorization: only request.user's payments are returned.
    """
    payments = Payment.objects.filter(user=request.user).order_by('-received_at')
    return render(request, 'payments/history.html', {'payments': payments})


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
