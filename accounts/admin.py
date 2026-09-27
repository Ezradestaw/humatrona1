from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import User, DeviceTrialSignal, ApprovedEducationalDomain, StudentVerification
from audit.services import log_admin_action


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        'email',
        'first_name',
        'last_name',
        'country',
        'job_title',
        'is_email_verified',
        'is_active',
        'trial_used',
        'date_joined',
    )
    list_filter = (
        'is_email_verified',
        'is_active',
        'trial_used',
        'country',
        'job_title',
        'date_joined',
    )
    search_fields = ('email', 'first_name', 'last_name', 'phone_number')
    ordering = ('-date_joined',)

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {
            'fields': (
                'first_name',
                'last_name',
                'phone_number',
                'country',
                'job_title',
                'job_title_other',
                'sex',
            )
        }),
        ('Permissions & Status', {
            'fields': (
                'is_active',
                'is_email_verified',
                'trial_used',
                'is_staff',
                'is_superuser',
                'groups',
                'user_permissions',
            )
        }),
        ('Device & Anti-Abuse', {
            'fields': ('device_fingerprint',),
            'classes': ('collapse',),
        }),
        ('Important Dates', {'fields': ('last_login', 'date_joined')}),
    )

    readonly_fields = ('last_login', 'date_joined', 'device_fingerprint')

    actions = ['verify_selected_emails', 'disable_selected_accounts', 'enable_selected_accounts']

    @admin.action(description="Mark selected users as email-verified and active")
    def verify_selected_emails(self, request, queryset):
        for user in queryset:
            user.is_email_verified = True
            user.is_active = True
            user.save(update_fields=['is_email_verified', 'is_active'])
            log_admin_action(request, 'user_verified', user.email, {'user_id': user.id})
        self.message_user(request, f"{queryset.count()} user(s) verified.")

    @admin.action(description="Disable selected accounts")
    def disable_selected_accounts(self, request, queryset):
        for user in queryset:
            user.is_active = False
            user.save(update_fields=['is_active'])
            log_admin_action(request, 'user_disabled', user.email, {'user_id': user.id})
        self.message_user(request, f"{queryset.count()} account(s) disabled.")

    @admin.action(description="Enable selected accounts")
    def enable_selected_accounts(self, request, queryset):
        for user in queryset:
            user.is_active = True
            user.save(update_fields=['is_active'])
            log_admin_action(request, 'user_enabled', user.email, {'user_id': user.id})
        self.message_user(request, f"{queryset.count()} account(s) enabled.")


@admin.register(DeviceTrialSignal)
class DeviceTrialSignalAdmin(admin.ModelAdmin):
    list_display = ('fingerprint_hash_short', 'user', 'ip_address', 'trials_count', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('fingerprint_hash', 'user__email', 'ip_address')
    readonly_fields = ('fingerprint_hash', 'user', 'ip_address', 'trials_count', 'created_at', 'updated_at')

    def fingerprint_hash_short(self, obj):
        return f"{obj.fingerprint_hash[:16]}..."
    fingerprint_hash_short.short_description = 'Fingerprint Hash'


@admin.register(ApprovedEducationalDomain)
class ApprovedEducationalDomainAdmin(admin.ModelAdmin):
    list_display = ('domain', 'institution_name', 'country', 'is_active', 'created_at')
    list_filter = ('is_active', 'country')
    search_fields = ('domain', 'institution_name', 'country')
    list_editable = ('is_active',)


@admin.register(StudentVerification)
class StudentVerificationAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'educational_email',
        'educational_institution',
        'educational_email_verified',
        'student_id_expiration_date',
        'status',
        'is_discount_active',
        'submitted_at',
        'reviewed_by',
    )
    list_filter = ('status', 'educational_email_verified', 'created_at')
    search_fields = ('user__email', 'educational_email', 'educational_institution')
    readonly_fields = (
        'submitted_at',
        'verified_at',
        'rejected_at',
        'reviewed_by',
        'reviewed_at',
        'created_at',
        'updated_at',
        'view_document_link',
    )
    fieldsets = (
        ('User & Contact', {
            'fields': ('user', 'educational_email', 'educational_institution', 'educational_domain', 'educational_email_verified')
        }),
        ('Student ID Credentials', {
            'fields': ('student_id_file', 'view_document_link', 'student_id_expiration_date')
        }),
        ('Verification Status & Review', {
            'fields': ('status', 'rejection_reason', 'reviewed_by', 'reviewed_at', 'verified_at', 'rejected_at')
        }),
        ('Audit Timestamps', {
            'fields': ('submitted_at', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    actions = ['approve_verifications', 'reject_verifications']

    def is_discount_active(self, obj):
        return obj.is_active_and_verified
    is_discount_active.boolean = True
    is_discount_active.short_description = '25% Discount Active'

    def view_document_link(self, obj):
        if obj.student_id_file:
            from django.urls import reverse
            url = reverse('accounts:student_id_document', args=[obj.id])
            return format_html('<a href="{}" target="_blank" class="button">View / Download Document</a>', url)
        return "No file uploaded"
    view_document_link.short_description = 'Student ID Document'

    @admin.action(description="Approve selected student verifications (Grant 25% Discount)")
    def approve_verifications(self, request, queryset):
        from django.utils import timezone
        from notifications.services import EmailService
        count = 0
        for sv in queryset:
            sv.status = StudentVerification.STATUS_VERIFIED
            sv.verified_at = timezone.now()
            sv.reviewed_by = request.user
            sv.reviewed_at = timezone.now()
            sv.rejection_reason = ''
            sv.save()
            EmailService.send_student_verification_approved_email(sv.user)
            log_admin_action(request, 'student_verification_approved', sv.user.email, {'verification_id': sv.id})
            count += 1
        self.message_user(request, f"{count} student verification(s) approved and notifications sent.")

    @admin.action(description="Reject selected student verifications")
    def reject_verifications(self, request, queryset):
        from django.utils import timezone
        from notifications.services import EmailService
        count = 0
        for sv in queryset:
            reason = sv.rejection_reason or "Student ID document or educational credentials could not be verified."
            sv.status = StudentVerification.STATUS_REJECTED
            sv.rejected_at = timezone.now()
            sv.reviewed_by = request.user
            sv.reviewed_at = timezone.now()
            sv.rejection_reason = reason
            sv.save()
            EmailService.send_student_verification_rejected_email(sv.user, reason)
            log_admin_action(request, 'student_verification_rejected', sv.user.email, {'verification_id': sv.id, 'reason': reason})
            count += 1
        self.message_user(request, f"{count} student verification(s) rejected and notifications sent.")

