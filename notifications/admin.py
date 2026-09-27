from django.contrib import admin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient_email', 'notification_type', 'subject', 'is_sent', 'created_at')
    list_filter = ('notification_type', 'is_sent', 'created_at')
    search_fields = ('recipient_email', 'subject', 'body')
    readonly_fields = ('created_at',)
