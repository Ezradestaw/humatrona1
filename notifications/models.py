from django.conf import settings
from django.db import models


class Notification(models.Model):
    """Tracks email and system notifications dispatched to users."""
    NOTIFICATION_TYPES = [
        ('email_verification', 'Email Verification'),
        ('password_reset', 'Password Reset'),
        ('subscription_activated', 'Subscription Activated'),
        ('subscription_expiring', 'Subscription Expiring Soon'),
        ('subscription_expired', 'Subscription Expired'),
        ('payment_received', 'Payment Received'),
        ('payment_failed', 'Payment Verification Failed'),
        ('pdf_completed', 'PDF Processing Completed'),
        ('pdf_failed', 'PDF Processing Failed'),
        ('contact_message', 'Admin Contact Notification'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        null=True,
        blank=True
    )
    recipient_email = models.EmailField()
    notification_type = models.CharField(max_length=64, choices=NOTIFICATION_TYPES)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    is_sent = models.BooleanField(default=False)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient_email']),
            models.Index(fields=['notification_type']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"[{self.notification_type}] to {self.recipient_email} at {self.created_at:%Y-%m-%d %H:%M}"
