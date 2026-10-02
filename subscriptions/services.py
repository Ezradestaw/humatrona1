from datetime import timedelta
import logging
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .models import Subscription, SubscriptionPlan
from notifications.services import EmailService

logger = logging.getLogger('humatron')


class PricingCalculator:
    """
    Authoritative server-side pricing calculation engine with Decimal arithmetic.
    Retrieves plan prices strictly from database plan configuration.
    """

    @classmethod
    def calculate(cls, plan, user=None):
        original_usd = Decimal(str(plan.price))
        final_usd = original_usd
        discount_usd = Decimal('0.00')

        has_configured_etb = (plan.price_etb is not None)
        if has_configured_etb:
            original_etb = Decimal(str(plan.price_etb))
            final_etb = original_etb
            discount_etb = Decimal('0.00')
        else:
            original_etb = None
            discount_etb = None
            final_etb = None

        return {
            'original_usd': original_usd,
            'discount_usd': discount_usd,
            'final_usd': final_usd,
            'has_configured_etb': has_configured_etb,
            'original_etb': original_etb,
            'discount_etb': discount_etb,
            'final_etb': final_etb,
            'discount_percentage': Decimal('0.00'),
        }


class SubscriptionService:
    """Authoritative business logic for plans, subscriptions, renewals, and quotas."""

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
        """Determines if the user can use the 1-time free PDF trial."""
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
        Authoritative verification pipeline:
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
            # Check unlimited vs quota-limited
            if sub.is_unlimited:
                # Backend fair-use server protection against automated abuse
                fair_use_limit = getattr(settings, 'UNLIMITED_PLAN_FAIR_USE_LIMIT', 5000)
                if sub.used_count >= fair_use_limit:
                    return False, f"Fair-use limit reached ({sub.used_count} of {fair_use_limit} PDFs used this month). Please contact support for high-volume enterprise needs.", False, sub.plan.max_file_size, max_pages
            else:
                if sub.remaining_quota <= 0:
                    return False, f"You have reached your subscription limit of {sub.pdf_limit} PDFs ({sub.used_count} of {sub.pdf_limit} PDFs used this month). Please upgrade or renew your plan.", False, sub.plan.max_file_size, max_pages

            allowed_size_mb = sub.plan.max_file_size or max_upload_size_mb
            allowed_pages = max_pages

            if file_size_bytes > (allowed_size_mb * 1024 * 1024):
                return False, f"File size exceeds plan limit of {allowed_size_mb} MB.", False, allowed_size_mb, allowed_pages

            if page_count > allowed_pages:
                return False, f"Document pages ({page_count}) exceed plan limit of {allowed_pages} pages.", False, allowed_size_mb, allowed_pages

            return True, "Authorized by active subscription.", False, allowed_size_mb, allowed_pages

        # 2. Check 1 free PDF trial
        if cls.is_trial_available(user):
            trial_max_size_mb = 10
            trial_max_pages = 50

            if file_size_bytes > (trial_max_size_mb * 1024 * 1024):
                return False, f"File size exceeds Free Trial limit of {trial_max_size_mb} MB.", True, trial_max_size_mb, trial_max_pages

            if page_count > trial_max_pages:
                return False, f"Document pages ({page_count}) exceed Free Trial limit of {trial_max_pages} pages.", True, trial_max_size_mb, trial_max_pages

            return True, "Authorized by 1 Free Trial PDF.", True, trial_max_size_mb, trial_max_pages

        return False, "You do not have an active subscription or free trial remaining. Please subscribe to continue.", False, 0, 0

    @classmethod
    @transaction.atomic
    def activate_subscription(cls, user, plan, payment_method, duration_days=None,
                              payment_country=""):
        """
        Activates or renews a subscription atomically inside a database transaction.
        For renewals:
        - If an existing subscription is still active, extend from the existing expiration date.
        - If expired or new, start from the approval date (now) and extend 1 month (30 days).
        Idempotent and atomic to prevent duplicate subscription activation.
        """
        now = timezone.now()
        days = duration_days or plan.duration_days or 30

        # Check for active existing subscription
        active_sub = Subscription.objects.filter(
            user=user,
            status=Subscription.STATUS_ACTIVE
        ).order_by('-end_date').first()

        if active_sub and active_sub.end_date and active_sub.end_date > now:
            # Renewal of currently active subscription: extend from existing expiration date
            start_date = active_sub.start_date or now
            end_date = active_sub.end_date + timedelta(days=days)
            active_sub.status = Subscription.STATUS_CANCELLED
            active_sub.save(update_fields=['status'])
        else:
            # Expired or new subscription: start from approval date (now)
            start_date = now
            end_date = now + timedelta(days=days)
            # Expire any prior stale records
            Subscription.objects.filter(
                user=user,
                status=Subscription.STATUS_ACTIVE
            ).update(status=Subscription.STATUS_EXPIRED)

        sub = Subscription.objects.create(
            user=user,
            plan=plan,
            status=Subscription.STATUS_ACTIVE,
            start_date=start_date,
            end_date=end_date,
            pdf_limit=plan.usage_limit if plan.usage_limit is not None else 50,
            used_count=0,
            payment_method=payment_method,
            payment_country=payment_country or getattr(user, 'country', ''),
        )

        EmailService.send_subscription_activated_email(user, sub)
        logger.info("Subscription activated for user %s: Plan %s, Valid until %s",
                    user.email, plan.name, end_date)
        return sub
