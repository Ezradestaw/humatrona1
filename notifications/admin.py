from django.contrib import admin, messages
from django.urls import path
from django.shortcuts import render, redirect
from django.conf import settings
from .models import Notification
from .services import EmailService


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient_email', 'notification_type', 'subject', 'is_sent', 'created_at')
    list_filter = ('notification_type', 'is_sent', 'created_at')
    search_fields = ('recipient_email', 'subject', 'body')
    readonly_fields = ('created_at',)
    change_list_template = 'admin/notifications/notification/change_list.html'
    actions = ['send_smtp_test_to_admin']

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('smtp-test/', self.admin_site.admin_view(self.smtp_test_view), name='notifications_smtp_test'),
        ]
        return custom_urls + urls

    def smtp_test_view(self, request):
        if not request.user.is_staff:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied

        admin_email = getattr(settings, 'ADMIN_EMAIL', 'admin@humatron.me')
        if request.method == 'POST':
            recipient = request.POST.get('recipient_email', '').strip()
            mailbox = request.POST.get('mailbox', 'support').strip()
            success, msg = EmailService.send_smtp_test_email(recipient, mailbox=mailbox)
            if success:
                messages.success(request, f"SMTP test email sent successfully to {recipient} via {mailbox}@humatron.me.")
                return redirect('admin:notifications_notification_changelist')
            else:
                messages.error(request, f"SMTP test failed: {msg}")

        context = {
            **self.admin_site.each_context(request),
            'admin_email': admin_email,
            'title': 'SMTP Test Tool',
        }
        return render(request, 'admin/notifications/smtp_test.html', context)

    @admin.action(description="Send SMTP test email to admin@humatron.me")
    def send_smtp_test_to_admin(self, request, queryset):
        admin_email = getattr(settings, 'ADMIN_EMAIL', 'admin@humatron.me')
        success, msg = EmailService.send_smtp_test_email(admin_email, mailbox='support')
        if success:
            self.message_user(request, f"SMTP test email sent successfully to {admin_email}.")
        else:
            self.message_user(request, f"SMTP test failed: {msg}", level=messages.ERROR)
