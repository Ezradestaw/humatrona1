from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from .models import SubscriptionPlan, Subscription
from .services import SubscriptionService


def plans_view(request):
    """Public & authenticated subscription plans page."""
    plans = SubscriptionPlan.objects.filter(active=True).order_by('sort_order', 'price')
    
    current_sub = None
    user_country = 'Other'
    if request.user.is_authenticated:
        current_sub = SubscriptionService.get_active_subscription(request.user)
        user_country = request.user.country

    is_ethiopia = (user_country.lower() == 'ethiopia')

    context = {
        'plans': plans,
        'current_subscription': current_sub,
        'user_country': user_country,
        'is_ethiopia': is_ethiopia,
    }
    return render(request, 'subscriptions/plans.html', context)


@login_required
def my_subscription_view(request):
    """User subscription status page (Section 36)."""
    user = request.user
    subscription = SubscriptionService.get_active_subscription(user)
    trial_available = SubscriptionService.is_trial_available(user)
    all_subscriptions = Subscription.objects.filter(user=user).order_by('-created_at')

    context = {
        'subscription': subscription,
        'trial_available': trial_available,
        'all_subscriptions': all_subscriptions,
    }
    return render(request, 'subscriptions/my_subscription.html', context)


@login_required
def cancel_subscription_view(request, subscription_id):
    subscription = get_object_or_404(Subscription, id=subscription_id, user=request.user)
    if request.method == 'POST':
        subscription.status = Subscription.STATUS_CANCELLED
        subscription.save(update_fields=['status'])
        messages.success(request, f"Your '{subscription.plan.name}' subscription has been cancelled.")
        return redirect('subscriptions:my_subscription')

    return render(request, 'subscriptions/confirm_cancel.html', {'subscription': subscription})
