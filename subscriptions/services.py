from datetime import timedelta
import logging
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .models import Subscription, SubscriptionPlan
from notifications.services import EmailService

logger = logging.getLogger('humatron')


class SubscriptionService:
    """Authoritative business logic for plans, subscriptions, and quotas."""

    @classmethod
    def get_active_subscription(cls, user):
        """
        Retrieves the user's currently active subscription.
        Automatically expires subscriptions whose end_date has lapsed.
        """
        if not user or not user.is_authenticated:
            return None

        now = timezone.now()
        active_sub = Subscription.objects.filter(
            user=user,
            status=Subscription.STATUS_ACTIVE
        ).order_by('-created_at').first()

        if active_sub:
            if active_sub.end_date and now > active_sub.end_date:
                active_sub.status = Subscription.STATUS_EXPIRED
                active_sub.save(update_fields=['status'])
                EmailService.send_subscription_expired_email(user, active_sub)
                return None
            return active_sub

        return None

    @classmethod
    def is_trial_available(cls, user):
        """Determines if the user can use the 1-time free PDF trial (Sec 23)."""
        if not user or not user.is_authenticated:
            return False
        if not user.is_email_verified:
            return False
        if user.trial_used:
            return False
        
        # If user already has an active subscription, they don't need trial
        if cls.get_active_subscription(user):
            return False
        return True

    @classmethod
    def can_process_pdf(cls, user, file_size_bytes=0, page_count=0):
        """
        Section 22: Authoritative verification pipeline:
        Authenticated? -> Email verified? -> Subscription/trial valid? -> Usage remaining? -> File within limits?
        Returns tuple: (is_allowed: bool, message: str, is_trial: bool, max_size_mb: int, max_pages: int)
        """
        if not user or not user.is_authenticated:
            return False, "Authentication is required to process documents.", False, 0, 0

        if not user.is_email_verified:
            return False, "Please verify your email address before processing documents.", False, 0, 0

        max_upload_size_mb = getattr(settings, 'MAX_UPLOAD_SIZE_MB', 50)
        max_pages = getattr(settings, 'MAX_PAGES', 200)

        # 1. Check active subscription
        sub = cls.get_active_subscription(user)
        if sub:
            if sub.remaining_quota <= 0:
                return False, f"You have reached your subscription limit of {sub.pdf_limit} PDFs. Please renew or upgrade.", False, sub.plan.max_file_size_mb, sub.plan.max_pages_per_pdf

            allowed_size_mb = sub.plan.max_file_size_mb or max_upload_size_mb
            allowed_pages = sub.plan.max_pages_per_pdf or max_pages

            if file_size_bytes > (allowed_size_mb * 1024 * 1024):
                return False, f"File size exceeds plan limit of {allowed_size_mb} MB.", False, allowed_size_mb, allowed_pages

            if page_count > allowed_pages:
                return False, f"Document pages ({page_count}) exceed plan limit of {allowed_pages} pages.", False, allowed_size_mb, allowed_pages

            return True, "Authorized by active subscription.", False, allowed_size_mb, allowed_pages

        # 2. Check 1 free PDF trial
        if cls.is_trial_available(user):
            trial_max_size_mb = 25
            trial_max_pages = 50

            if file_size_bytes > (trial_max_size_mb * 1024 * 1024):
                return False, f"File size exceeds Free Trial limit of {trial_max_size_mb} MB.", True, trial_max_size_mb, trial_max_pages

            if page_count > trial_max_pages:
                return False, f"Document pages ({page_count}) exceed Free Trial limit of {trial_max_pages} pages.", True, trial_max_size_mb, trial_max_pages

            return True, "Authorized by 1 Free Trial PDF.", True, trial_max_size_mb, trial_max_pages

        return False, "You do not have an active subscription or free trial remaining. Please subscribe to continue.", False, 0, 0

    @classmethod
    @transaction.atomic
    def activate_subscription(cls, user, plan, payment_method, duration_days=None):
        """
        Activates a subscription atomically inside a database transaction.
        Transitions any previous active subscription to EXPIRED.
        """
        now = timezone.now()
        days = duration_days or plan.duration_days
        end_date = now + timedelta(days=days)

        # Mark prior active subscriptions as replaced/expired
        Subscription.objects.filter(
            user=user,
            status=Subscription.STATUS_ACTIVE
        ).update(status=Subscription.STATUS_CANCELLED)

        sub = Subscription.objects.create(
            user=user,
            plan=plan,
            status=Subscription.STATUS_ACTIVE,
            start_date=now,
            end_date=end_date,
            pdf_limit=plan.pdf_limit,
            used_count=0,
            payment_method=payment_method
        )

        EmailService.send_subscription_activated_email(user, sub)
        logger.info("Subscription activated for user %s: Plan %s, Valid until %s", user.email, plan.name, end_date)
        return sub
