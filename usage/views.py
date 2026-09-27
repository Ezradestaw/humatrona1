from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import UsageRecord
from subscriptions.services import SubscriptionService


@login_required
def usage_view(request):
    """User usage history and metrics (Section 36)."""
    user = request.user
    subscription = SubscriptionService.get_active_subscription(user)
    records = UsageRecord.objects.filter(user=user).select_related('processing_job', 'subscription').order_by('-timestamp')

    context = {
        'subscription': subscription,
        'records': records,
    }
    return render(request, 'usage/usage.html', context)
