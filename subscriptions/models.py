from django.conf import settings
from django.db import models
from django.utils import timezone


class SubscriptionPlan(models.Model):
    """
    Configurable subscription plan.
    Supports four configurable choices: FREE, BASIC, PRO, UNLIMITED.
    Prices and limits are managed strictly from Django Admin.
    """
    PRIORITY_NORMAL = 'Normal'
    PRIORITY_HIGHER = 'Higher than Free'
    PRIORITY_HIGH = 'High'
    PRIORITY_HIGHEST = 'Highest'

    PRIORITY_CHOICES = [
        (PRIORITY_NORMAL, 'Normal'),
        (PRIORITY_HIGHER, 'Higher than Free'),
        (PRIORITY_HIGH, 'High'),
        (PRIORITY_HIGHEST, 'Highest'),
    ]

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=50, unique=True, default='')
    code = models.SlugField(max_length=50, blank=True, null=True, help_text="Legacy alias for slug")
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    currency = models.CharField(max_length=3, default='USD')
    billing_period = models.CharField(max_length=50, default='month')
    usage_limit = models.PositiveIntegerField(
        default=50,
        help_text="Total PDFs allowed per billing period (0 denotes unlimited)"
    )
    max_file_size = models.PositiveIntegerField(
        default=50,
        help_text="Maximum upload size in Megabytes (MB)"
    )
    processing_priority = models.CharField(
        max_length=50,
        choices=PRIORITY_CHOICES,
        default=PRIORITY_NORMAL,
        help_text="Processing priority tier"
    )
    features = models.JSONField(
        default=list,
        blank=True,
        help_text="List of feature bullet points for the pricing card"
    )
    price_etb = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional Telebirr price in Ethiopian Birr, configured by administrator"
    )
    duration_days = models.PositiveIntegerField(default=30)
    active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'price']

    def __str__(self):
        limit_text = "Unlimited" if self.usage_limit == 0 else f"{self.usage_limit} PDFs"
        return f"{self.name} (${self.price} {self.currency}/{self.billing_period} - {limit_text})"

    def __init__(self, *args, **kwargs):
        if 'max_pages_per_pdf' in kwargs:
            self._max_pages_per_pdf = kwargs.pop('max_pages_per_pdf')
        if 'pdf_limit' in kwargs and 'usage_limit' not in kwargs:
            kwargs['usage_limit'] = kwargs.pop('pdf_limit')
        elif 'pdf_limit' in kwargs:
            kwargs.pop('pdf_limit')
        if 'max_file_size_mb' in kwargs and 'max_file_size' not in kwargs:
            kwargs['max_file_size'] = kwargs.pop('max_file_size_mb')
        elif 'max_file_size_mb' in kwargs:
            kwargs.pop('max_file_size_mb')
        if 'code' in kwargs and 'slug' not in kwargs:
            kwargs['slug'] = kwargs['code']
        elif 'slug' in kwargs and 'code' not in kwargs:
            kwargs['code'] = kwargs['slug']
        elif 'name' in kwargs and 'slug' not in kwargs:
            from django.utils.text import slugify
            kwargs['slug'] = slugify(kwargs['name'])
            if 'code' not in kwargs:
                kwargs['code'] = kwargs['slug']
        super().__init__(*args, **kwargs)

    def save(self, *args, **kwargs):
        if not self.slug and self.code:
            self.slug = self.code
        elif not self.code and self.slug:
            self.code = self.slug
        elif not self.slug and not self.code and self.name:
            from django.utils.text import slugify
            self.slug = slugify(self.name)
            self.code = self.slug
        super().save(*args, **kwargs)

    @property
    def pdf_limit(self):
        return self.usage_limit

    @pdf_limit.setter
    def pdf_limit(self, value):
        self.usage_limit = value

    @property
    def max_file_size_mb(self):
        return self.max_file_size

    @max_file_size_mb.setter
    def max_file_size_mb(self, value):
        self.max_file_size = value

    @property
    def max_pages_per_pdf(self):
        return getattr(self, '_max_pages_per_pdf', 200)

    @max_pages_per_pdf.setter
    def max_pages_per_pdf(self, value):
        self._max_pages_per_pdf = value

    @property
    def is_unlimited(self):
        return self.usage_limit == 0


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
    pdf_limit = models.PositiveIntegerField(help_text="0 denotes unlimited")
    used_count = models.PositiveIntegerField(default=0)
    payment_method = models.CharField(max_length=32, blank=True)
    payment_country = models.CharField(max_length=100, blank=True)
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
    def is_unlimited(self):
        return self.pdf_limit == 0 or (self.plan and self.plan.usage_limit == 0)

    @property
    def is_valid(self):
        """Authoritative server check for active status and date validity."""
        if self.status != self.STATUS_ACTIVE:
            return False
        if self.end_date and timezone.now() > self.end_date:
            return False
        if not self.is_unlimited and self.remaining_quota <= 0:
            return False
        return True

    @property
    def remaining_quota(self):
        if self.is_unlimited:
            return 999999
        return max(0, self.pdf_limit - self.used_count)
