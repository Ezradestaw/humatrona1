from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import User, DeviceTrialSignal
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
