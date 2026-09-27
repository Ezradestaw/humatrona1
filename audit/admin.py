from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'administrator', 'action', 'target', 'ip_address')
    list_filter = ('action', 'timestamp')
    search_fields = ('target', 'administrator__email', 'ip_address')
    readonly_fields = ('administrator', 'action', 'target', 'metadata', 'ip_address', 'timestamp')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
