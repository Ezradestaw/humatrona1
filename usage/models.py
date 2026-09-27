from django.conf import settings
from django.db import models


class UsageRecord(models.Model):
    """
    Tracks consumption of PDF processing allowances (Section 25).
    Guarantees idempotency via OneToOne relation with PDFProcessingJob.
    """
    TYPE_TRIAL = 'trial'
    TYPE_SUBSCRIPTION = 'subscription'

    TYPE_CHOICES = [
        (TYPE_TRIAL, 'Free Trial'),
        (TYPE_SUBSCRIPTION, 'Subscription Quota'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='usage_records'
    )
    subscription = models.ForeignKey(
        'subscriptions.Subscription',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='usage_records'
    )
    processing_job = models.OneToOneField(
        'pdf_processor.PDFProcessingJob',
        on_delete=models.CASCADE,
        related_name='usage_record'
    )
    usage_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    quantity = models.PositiveIntegerField(default=1)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['usage_type']),
        ]

    def __str__(self):
        return f"Usage: {self.user.email} - {self.quantity} PDF ({self.usage_type}) at {self.timestamp:%Y-%m-%d %H:%M}"
