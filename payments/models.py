from django.conf import settings
from django.db import models


class Payment(models.Model):
    """
    Unified payment model for PayPal and Telebirr (Sections 27, 28, 29, 30).
    Features database-level unique constraints preventing double activation.
    """
    PROVIDER_PAYPAL = 'paypal'
    PROVIDER_TELEBIRR = 'telebirr'

    PROVIDER_CHOICES = [
        (PROVIDER_PAYPAL, 'PayPal'),
        (PROVIDER_TELEBIRR, 'Telebirr'),
    ]

    STATUS_RECEIVED = 'RECEIVED'
    STATUS_PENDING = 'PENDING'
    STATUS_VERIFIED = 'VERIFIED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_DUPLICATE = 'DUPLICATE'
    STATUS_FAILED = 'FAILED'

    STATUS_CHOICES = [
        (STATUS_RECEIVED, 'Received'),
        (STATUS_PENDING, 'Pending'),
        (STATUS_VERIFIED, 'Verified'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_DUPLICATE, 'Duplicate'),
        (STATUS_FAILED, 'Failed'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, db_index=True)
    transaction_id = models.CharField(max_length=128, db_index=True)
    plan = models.ForeignKey(
        'subscriptions.SubscriptionPlan',
        on_delete=models.PROTECT,
        related_name='payments',
        null=True,
        blank=True
    )
    subscription = models.ForeignKey(
        'subscriptions.Subscription',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments'
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=5, default='USD')
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_RECEIVED,
        db_index=True
    )
    raw_message = models.TextField(blank=True, help_text="Original Telebirr SMS or webhook payload")
    message_hash = models.CharField(max_length=64, blank=True, db_index=True)
    merchant_account = models.CharField(max_length=100, blank=True)
    sender_info = models.CharField(max_length=100, blank=True)
    rejection_reason = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-received_at']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'transaction_id'],
                name='unique_provider_transaction_id'
            )
        ]
        indexes = [
            models.Index(fields=['user', 'received_at']),
            models.Index(fields=['status', 'provider']),
            models.Index(fields=['transaction_id']),
        ]

    def __str__(self):
        return f"{self.provider.upper()} {self.transaction_id} - {self.currency} {self.amount} ({self.status})"
