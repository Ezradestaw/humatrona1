import logging
from django.db import transaction
from django.db.models import Count, Sum
from .models import UsageRecord

logger = logging.getLogger('humatron')


class UsageService:
    """Authoritative idempotent usage deduction engine (Section 25)."""

    @classmethod
    def record_job_usage(cls, job):
        """
        Deducts usage quota for a successfully completed processing job.
        Strictly idempotent: will never deduct twice for the same job.
        """
        # Idempotency check: see if record already exists
        existing = UsageRecord.objects.filter(processing_job=job).first()
        if existing:
            logger.info("Job %s already has usage record %s. Skipping deduction.", job.id, existing.id)
            return existing

        user = job.user
        with transaction.atomic():
            # Check if there is an active subscription at job time
            from subscriptions.services import SubscriptionService
            active_sub = SubscriptionService.get_active_subscription(user)

            if active_sub:
                active_sub.used_count += 1
                active_sub.save(update_fields=['used_count'])
                usage_type = UsageRecord.TYPE_SUBSCRIPTION
                record_sub = active_sub
            else:
                # Free trial consumption
                user.trial_used = True
                user.save(update_fields=['trial_used'])
                usage_type = UsageRecord.TYPE_TRIAL
                record_sub = None

                # Increment device trial signal if present
                if user.device_fingerprint:
                    from accounts.models import DeviceTrialSignal
                    signal = DeviceTrialSignal.objects.filter(user=user).first()
                    if signal:
                        signal.trials_count += 1
                        signal.save(update_fields=['trials_count'])

            record = UsageRecord.objects.create(
                user=user,
                subscription=record_sub,
                processing_job=job,
                usage_type=usage_type,
                quantity=1
            )
            logger.info("Recorded usage for job %s: user %s (%s)", job.id, user.email, usage_type)
            return record

    @classmethod
    def get_summary_statistics(cls):
        """Administrative analytics summary (Section 42)."""
        from pdf_processor.models import PDFProcessingJob
        total_jobs = PDFProcessingJob.objects.count()
        completed_jobs = PDFProcessingJob.objects.filter(status='COMPLETED').count()
        failed_jobs = PDFProcessingJob.objects.filter(status='FAILED').count()
        total_usage_count = UsageRecord.objects.count()

        top_users = (
            UsageRecord.objects.values('user__email')
            .annotate(total=Count('id'))
            .order_by('-total')[:10]
        )

        return {
            'total_jobs': total_jobs,
            'completed_jobs': completed_jobs,
            'failed_jobs': failed_jobs,
            'total_usage_count': total_usage_count,
            'top_users': top_users,
        }
