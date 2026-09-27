from datetime import timedelta
import logging
from celery import shared_task
from django.utils import timezone
from .models import Subscription
from notifications.services import EmailService

logger = logging.getLogger('humatron')


@shared_task
def check_expiring_subscriptions_task():
    """
    Daily background worker checking for expiring and expired subscriptions.
    Dispatches notifications per Section 33.
    """
    now = timezone.now()
    three_days_from_now = now + timedelta(days=3)

    # 1. Notify users whose subscriptions expire within 3 days
    expiring_soon = Subscription.objects.filter(
        status=Subscription.STATUS_ACTIVE,
        end_date__lte=three_days_from_now,
        end_date__gt=now,
        is_notified_expiring=False
    )
    for sub in expiring_soon:
        days_left = max(1, (sub.end_date - now).days)
        EmailService.send_subscription_expiring_email(sub.user, sub, days_left)
        sub.is_notified_expiring = True
        sub.save(update_fields=['is_notified_expiring'])
        logger.info("Sent expiring reminder to user %s for sub %s", sub.user.email, sub.id)

    # 2. Mark elapsed subscriptions as EXPIRED
    expired_subs = Subscription.objects.filter(
        status=Subscription.STATUS_ACTIVE,
        end_date__lte=now
    )
    for sub in expired_subs:
        sub.status = Subscription.STATUS_EXPIRED
        sub.save(update_fields=['status'])
        EmailService.send_subscription_expired_email(sub.user, sub)
        logger.info("Marked sub %s for user %s as EXPIRED", sub.id, sub.user.email)

    return f"Processed {expiring_soon.count()} expiring reminders and {expired_subs.count()} expirations."
