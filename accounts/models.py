from django.contrib.auth.models import AbstractUser
from django.db import models


JOB_TITLE_CHOICES = [
    ('Academic', 'Academic'),
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
