from django.db import models


class ContactMessage(models.Model):
    """
    Contact messages submitted through website form (Sections 8, 43).
    Stored in PostgreSQL and dispatches administrator notification.
    """
    name = models.CharField(max_length=120)
    email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    is_read = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)
    admin_notes = models.TextField(blank=True, help_text="Internal notes by support/admin staff")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_read', 'is_resolved']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.subject} ({self.name} <{self.email}>)"
