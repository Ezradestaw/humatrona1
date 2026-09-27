from django.contrib import admin
from .models import ContactMessage


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('subject', 'name', 'email', 'is_read', 'is_resolved', 'created_at')
    list_filter = ('is_read', 'is_resolved', 'created_at')
    search_fields = ('name', 'email', 'subject', 'message', 'admin_notes')
    readonly_fields = ('name', 'email', 'subject', 'message', 'ip_address', 'created_at', 'updated_at')
    fields = ('name', 'email', 'subject', 'message', 'ip_address', 'is_read', 'is_resolved', 'admin_notes', 'created_at', 'updated_at')
    
    actions = ['mark_as_read', 'mark_as_resolved']

    @admin.action(description="Mark selected messages as read")
    def mark_as_read(self, request, queryset):
        queryset.update(is_read=True)
        self.message_user(request, f"{queryset.count()} message(s) marked as read.")

    @admin.action(description="Mark selected messages as resolved")
    def mark_as_resolved(self, request, queryset):
        queryset.update(is_resolved=True, is_read=True)
        self.message_user(request, f"{queryset.count()} message(s) marked as resolved.")
