from django.contrib.auth.models import AbstractUser
from django.db import models


JOB_TITLE_CHOICES = [
    ('Student', 'Student'),
    ('Teacher', 'Teacher'),
    ('Engineer', 'Engineer'),
    ('Developer', 'Developer'),
    ('Researcher', 'Researcher'),
    ('Business Owner', 'Business Owner'),
    ('Administrator', 'Administrator'),
    ('Other', 'Other'),
]

SEX_CHOICES = [
    ('prefer_not_to_say', 'Prefer not to say'),
    ('female', 'Female'),
    ('male', 'Male'),
    ('other', 'Other'),
]

# Standard ISO country list with Ethiopia prominently available
COUNTRY_CHOICES = [
    ('Ethiopia', 'Ethiopia'),
    ('United States', 'United States'),
    ('United Kingdom', 'United Kingdom'),
    ('Canada', 'Canada'),
    ('Germany', 'Germany'),
    ('France', 'France'),
    ('Kenya', 'Kenya'),
    ('Nigeria', 'Nigeria'),
    ('South Africa', 'South Africa'),
    ('Egypt', 'Egypt'),
    ('India', 'India'),
    ('China', 'China'),
    ('Japan', 'Japan'),
    ('Australia', 'Australia'),
    ('Netherlands', 'Netherlands'),
    ('Sweden', 'Sweden'),
    ('United Arab Emirates', 'United Arab Emirates'),
    ('Other', 'Other Country'),
]


class User(AbstractUser):
    """Custom User model with verification, trial tracking, and profile fields."""
    email = models.EmailField('Email Address', unique=True, db_index=True)
    phone_number = models.CharField('Phone Number', max_length=32, blank=True)
    country = models.CharField('Country', max_length=100, choices=COUNTRY_CHOICES, default='Ethiopia')
    job_title = models.CharField('Job Title', max_length=64, choices=JOB_TITLE_CHOICES, default='Developer')
    job_title_other = models.CharField('Job Title (Other)', max_length=100, blank=True)
    sex = models.CharField('Sex', max_length=32, choices=SEX_CHOICES, default='prefer_not_to_say')
    
    is_email_verified = models.BooleanField('Email Verified', default=False)
    trial_used = models.BooleanField('Free Trial Consumed', default=False)
    device_fingerprint = models.CharField('Device Identifier Hash', max_length=128, blank=True, db_index=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'first_name', 'last_name']

    class Meta:
        ordering = ['-date_joined']
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['device_fingerprint']),
        ]

    def __str__(self):
        return f"{self.email} ({self.get_full_name() or self.username})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.username

    @property
    def is_verified_student(self):
        """
        Section 15: Returns True only when all student verification requirements are met:
        - Authenticated & account email verified
        - Student verification record exists with status VERIFIED
        - Educational email is verified
        - Student ID is not expired
        """
        if not self.is_authenticated or not self.is_email_verified:
            return False
        sv = getattr(self, 'student_verification', None)
        if sv:
            return sv.is_active_and_verified
        return False


class ApprovedEducationalDomain(models.Model):
    """
    Section 9: Configurable list of approved educational email domains.
    Administrators configure approved domains (e.g., aau.edu.et, mit.edu, stanford.edu).
    """
    domain = models.CharField(
        max_length=128,
        unique=True,
        db_index=True,
        help_text="Domain name without @ (e.g. aau.edu.et, mit.edu, oxford.ac.uk)"
    )
    institution_name = models.CharField(max_length=200, blank=True)
    country = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['domain']

    def __str__(self):
        return f"{self.domain} ({self.institution_name or 'Educational Institution'})"

    @classmethod
    def is_domain_approved(cls, email_address):
        """Validates whether an email's domain matches any active approved domain or suffix."""
        if not email_address or '@' not in email_address:
            return False
        domain_part = email_address.split('@')[-1].strip().lower()
        active_domains = cls.objects.filter(is_active=True).values_list('domain', flat=True)
        for d in active_domains:
            clean_d = d.strip().lower().lstrip('.')
            if domain_part == clean_d or domain_part.endswith('.' + clean_d):
                return True
        return False


class StudentVerification(models.Model):
    """
    Section 13: Student Verification model tracking educational email and ID verification.
    Grants 25% discount on subscriptions upon verification by administrator.
    """
    STATUS_NOT_SUBMITTED = 'NOT_SUBMITTED'
    STATUS_PENDING = 'PENDING'
    STATUS_EMAIL_VERIFIED = 'EMAIL_VERIFIED'
    STATUS_UNDER_REVIEW = 'UNDER_REVIEW'
    STATUS_VERIFIED = 'VERIFIED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_EXPIRED = 'EXPIRED'

    STATUS_CHOICES = [
        (STATUS_NOT_SUBMITTED, 'Not Submitted'),
        (STATUS_PENDING, 'Pending Educational Email Verification'),
        (STATUS_EMAIL_VERIFIED, 'Educational Email Verified'),
        (STATUS_UNDER_REVIEW, 'Under Administrator Review'),
        (STATUS_VERIFIED, 'Verified Student (25% Discount Active)'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_EXPIRED, 'Expired Student ID'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='student_verification'
    )
    educational_email = models.EmailField('Educational Email Address', blank=True, db_index=True)
    educational_institution = models.CharField('Educational Institution', max_length=255, blank=True)
    educational_domain = models.CharField(max_length=128, blank=True)
    educational_email_verified = models.BooleanField(default=False)
    student_id_file = models.FileField(
        upload_to='private/student_ids/',
        blank=True,
        help_text="Uploaded Student ID document (JPG, PNG, PDF)"
    )
    student_id_expiration_date = models.DateField(
        'Student ID Expiration Date',
        null=True,
        blank=True,
        help_text="Expiration date indicated on the student ID card"
    )
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_NOT_SUBMITTED,
        db_index=True
    )

    submitted_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_student_verifications'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['educational_email']),
        ]

    def __str__(self):
        return f"StudentVerification({self.user.email} - {self.status})"

    @property
    def is_active_and_verified(self):
        """
        Sections 12, 15, 25: Returns True if and only if:
        1. status is VERIFIED
        2. educational email is verified
        3. student_id_expiration_date is greater than or equal to current date
        """
        if self.status != self.STATUS_VERIFIED:
            return False
        if not self.educational_email_verified:
            return False
        if self.student_id_expiration_date:
            from django.utils import timezone
            if self.student_id_expiration_date < timezone.now().date():
                # Automatically mark expired (Section 25)
                self.status = self.STATUS_EXPIRED
                self.save(update_fields=['status'])
                return False
        return True


class DeviceTrialSignal(models.Model):
    """
    Privacy-conscious server-side device trial anti-abuse tracker.
    Used as an anti-abuse signal alongside account-level authoritative trial flags.
    """
    fingerprint_hash = models.CharField(max_length=64, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='device_trials')
    trials_count = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"DeviceSignal({self.fingerprint_hash[:10]}... | User: {self.user.email} | Trials: {self.trials_count})"
