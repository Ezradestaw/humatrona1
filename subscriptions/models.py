from django.conf import settings
from django.db import models
from django.utils import timezone


class SubscriptionPlan(models.Model):
    """
    Configurable subscription plan (Section 21).
    Supports four configurable choices with distinct USD and ETB pricing.
    """
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=50.00)
    currency = models.CharField(max_length=3, default='USD')
    price_etb = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Explicit Telebirr price in Ethiopian Birr, configured by administrator (Sec 1)"
    )
    duration_days = models.PositiveIntegerField(default=30)
    pdf_limit = models.PositiveIntegerField(default=25, help_text="Total PDFs allowed in this plan period")
    max_file_size_mb = models.PositiveIntegerField(default=50, help_text="Maximum upload size in Megabytes")
    max_pages_per_pdf = models.PositiveIntegerField(default=200, help_text="Maximum pages per document")
    active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'price']

    def __str__(self):
        return f"{self.name} (${self.price} {self.currency} - {self.pdf_limit} PDFs)"


class Subscription(models.Model):
    """User subscription instance tracking validity and quota."""
    STATUS_ACTIVE = 'ACTIVE'
    STATUS_EXPIRED = 'EXPIRED'
    STATUS_CANCELLED = 'CANCELLED'
    STATUS_PENDING = 'PENDING'
    STATUS_SUSPENDED = 'SUSPENDED'

    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_PENDING, 'Pending'),
        (STATUS_SUSPENDED, 'Suspended'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscriptions'
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name='user_subscriptions'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True
    )
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True, db_index=True)
    pdf_limit = models.PositiveIntegerField()
    used_count = models.PositiveIntegerField(default=0)
    payment_method = models.CharField(max_length=32, blank=True)
    payment_country = models.CharField(max_length=100, blank=True)
    student_discount_applied = models.BooleanField(default=False)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    is_notified_expiring = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['end_date']),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.plan.name} ({self.status})"

    @property
    def is_valid(self):
        """Authoritative server check for active status and date validity."""
        if self.status != self.STATUS_ACTIVE:
            return False
        if self.end_date and timezone.now() > self.end_date:
            return False
        if self.remaining_quota <= 0:
            return False
        return True

    @property
    def remaining_quota(self):
        return max(0, self.pdf_limit - self.used_count)
