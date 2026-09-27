from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """
    Audit log for sensitive administrator actions (Section 44).
    Tracks changes to users, plans, subscriptions, payments, and document deletions.
    """
    ACTION_CHOICES = [
        ('user_disabled', 'Admin Disabled User'),
        ('user_enabled', 'Admin Enabled User'),
        ('user_verified', 'Admin Manually Verified Email'),
        ('subscription_changed', 'Admin Changed Subscription'),
        ('plan_modified', 'Admin Modified Plan'),
        ('payment_reviewed', 'Admin Manually Reviewed Payment'),
        ('payment_status_changed', 'Admin Changed Payment Status'),
        ('document_deleted', 'Admin Deleted Document'),
        ('other', 'Other Action'),
    ]

    administrator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='admin_audit_logs'
    )
    action = models.CharField(max_length=64, choices=ACTION_CHOICES)
    target = models.CharField(max_length=255, help_text="Resource or identifier targeted")
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['action']),
            models.Index(fields=['timestamp']),
            models.Index(fields=['target']),
        ]

    def __str__(self):
        admin_name = self.administrator.email if self.administrator else 'System'
        return f"{admin_name} | {self.action} | {self.target} | {self.timestamp:%Y-%m-%d %H:%M}"
