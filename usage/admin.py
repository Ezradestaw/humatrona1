from django.contrib import admin
from .models import UsageRecord


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'usage_type', 'subscription', 'processing_job', 'quantity', 'timestamp')
    list_filter = ('usage_type', 'timestamp')
    search_fields = ('user__email', 'processing_job__original_filename')
    readonly_fields = ('user', 'subscription', 'processing_job', 'usage_type', 'quantity', 'timestamp')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
