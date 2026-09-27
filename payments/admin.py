from django.contrib import admin
from .models import Payment
from audit.services import log_admin_action


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'transaction_id',
        'provider',
        'user',
        'amount',
        'currency',
        'status',
        'plan',
        'received_at',
        'verified_at',
    )
    list_filter = ('provider', 'status', 'currency', 'received_at')
    search_fields = ('transaction_id', 'user__email', 'merchant_account', 'raw_message')
    readonly_fields = (
        'transaction_id',
        'provider',
        'user',
        'plan',
        'subscription',
        'amount',
        'currency',
        'raw_message',
        'message_hash',
        'merchant_account',
        'sender_info',
        'received_at',
        'verified_at',
    )

    actions = ['mark_as_reviewed']

    @admin.action(description="Audit and mark selected payments as reviewed")
    def mark_as_reviewed(self, request, queryset):
        for payment in queryset:
            log_admin_action(request, 'payment_reviewed', payment.transaction_id, {
                'provider': payment.provider,
                'status': payment.status,
                'amount': str(payment.amount),
                'user': payment.user.email
            })
        self.message_user(request, f"{queryset.count()} payment(s) marked in audit trail.")
