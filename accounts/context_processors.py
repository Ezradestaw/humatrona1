from django.conf import settings


def humatron_globals(request):
    """Context processor providing site constants and user status to templates."""
    context = {
        'SITE_DOMAIN': getattr(settings, 'SITE_DOMAIN', 'humatron.me'),
        'ADMIN_EMAIL': getattr(settings, 'ADMIN_EMAIL', 'admin@humatron.me'),
    }
    if request.user.is_authenticated:
        # Cache-efficient subscription and trial resolution
        from subscriptions.services import SubscriptionService
        subscription = SubscriptionService.get_active_subscription(request.user)
        trial_available = SubscriptionService.is_trial_available(request.user)
        context['user_subscription'] = subscription
        context['user_trial_available'] = trial_available
    return context
