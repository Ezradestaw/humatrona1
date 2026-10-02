from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils import timezone
from .models import (
    Payment,
    BinanceManualPayment,
    BinanceManualPaymentSettings,
    TelebirrPayment,
    TelebirrPaymentSettings,
)
from .services import PaymentService
from audit.services import log_admin_action


@admin.register(TelebirrPaymentSettings)
class TelebirrPaymentSettingsAdmin(admin.ModelAdmin):
    list_display = (
        '__str__',
        'receiver_name',
        'phone_number',
        'enabled',
        'updated_at',
    )
    fields = (
        'enabled',
        'receiver_name',
        'phone_number',
        'instructions',
        'updated_at',
    )
    readonly_fields = ('updated_at',)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BinanceManualPaymentSettings)
class BinanceManualPaymentSettingsAdmin(admin.ModelAdmin):
    list_display = (
        '__str__',
        'enabled',
        'receiving_identifier_type',
        'receiving_identifier',
        'has_qr_code',
        'updated_at',
    )
    fields = (
        'enabled',
        'receiving_identifier_type',
        'receiving_identifier',
        'qr_code',
        'qr_preview',
        'payment_instructions',
        'support_message',
        'updated_at',
    )
    readonly_fields = ('updated_at', 'qr_preview')

    def has_qr_code(self, obj):
        return bool(obj.qr_code)
    has_qr_code.boolean = True
    has_qr_code.short_description = "QR Code Set"

    def qr_preview(self, obj):
        if obj.qr_code:
            return format_html(
                '<img src="{}" style="max-height: 180px; border-radius: 4px; border: 1px solid #ccc; display: block; margin-top: 4px;">',
                obj.qr_code.url
            )
        return "No QR code uploaded."
    qr_preview.short_description = "QR Code Preview"

    def has_delete_permission(self, request, obj=None):
        return False  # Prevent deleting settings singleton


@admin.register(BinanceManualPayment)
class BinanceManualPaymentAdmin(admin.ModelAdmin):
    """
    Dedicated Binance Manual Payments administrative interface (Section 7).
    Allows administrators to inspect customer submissions, proof screenshots,
    and approve or reject transactions with atomic subscription activation and audit logging.
    """
    list_display = (
        'id',
        'user_link',
        'user_email',
        'plan_name',
        'formatted_amount',
        'transaction_id',
        'sender_identifier',
        'status_badge',
        'proof_file_link',
        'submitted_at',
        'reviewed_by',
    )
    list_filter = ('status', 'submitted_at', 'received_at')
    search_fields = (
        'transaction_id',
        'sender_identifier',
        'user__email',
        'user__username',
        'plan__name',
        'raw_message',
        'admin_notes',
    )
    readonly_fields = (
        'user',
        'plan',
        'subscription',
        'amount',
        'currency',
        'payment_method',
        'transaction_id',
        'sender_identifier',
        'proof_file_preview',
        'received_at',
        'submitted_at',
        'verified_at',
        'reviewed_at',
        'reviewed_by',
        'original_amount',
        'discount_amount',
        'final_amount',
        'payment_country',
    )
    fieldsets = (
        ('Customer Submission', {
            'fields': (
                'user',
                'plan',
                'amount',
                'currency',
                'payment_method',
                'transaction_id',
                'sender_identifier',
                'submitted_at',
                'raw_message',
                'proof_file',
                'proof_file_preview',
            )
        }),
        ('Verification & Decision', {
            'fields': (
                'status',
                'rejection_reason',
                'admin_notes',
                'reviewed_by',
                'reviewed_at',
                'verified_at',
                'subscription',
            )
        }),
        ('Pricing & Country Audit', {
            'classes': ('collapse',),
            'fields': (
                'payment_country',
                'original_amount',
                'discount_amount',
                'final_amount',
                'received_at',
            )
        }),
    )

    actions = ['approve_payments', 'reject_payments']

    def get_queryset(self, request):
        return super().get_queryset(request).filter(payment_method=Payment.METHOD_BINANCE_MANUAL)

    @admin.display(description="User")
    def user_link(self, obj):
        return obj.user.username if obj.user else "-"

    @admin.display(description="Email")
    def user_email(self, obj):
        return obj.user.email if obj.user else "-"

    @admin.display(description="Plan")
    def plan_name(self, obj):
        return obj.plan.name if obj.plan else "-"

    @admin.display(description="Amount")
    def formatted_amount(self, obj):
        return f"{obj.currency} {obj.amount}"

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            Payment.STATUS_PENDING: '#d97706',
            Payment.STATUS_APPROVED: '#16a34a',
            Payment.STATUS_VERIFIED: '#16a34a',
            Payment.STATUS_REJECTED: '#dc2626',
            Payment.STATUS_CANCELLED: '#6b7280',
        }
        color = colors.get(obj.status, '#374151')
        return format_html(
            '<span style="color: white; background-color: {}; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">{}</span>',
            color,
            obj.status
        )

    @admin.display(description="Proof")
    def proof_file_link(self, obj):
        if obj.proof_file:
            return format_html('<a href="{}" target="_blank" style="font-weight: 600;">View Proof &nearr;</a>', obj.proof_file.url)
        return "-"

    @admin.display(description="Proof File Preview")
    def proof_file_preview(self, obj):
        if obj.proof_file:
            ext = obj.proof_file.name.lower().split('.')[-1]
            if ext in ('png', 'jpg', 'jpeg', 'webp'):
                return format_html(
                    '<a href="{}" target="_blank"><img src="{}" style="max-height: 300px; border-radius: 6px; border: 1px solid #ccc; display: block; margin-top: 6px;"></a>',
                    obj.proof_file.url,
                    obj.proof_file.url
                )
            return format_html(
                '<a href="{}" target="_blank" class="button" style="padding: 6px 12px; margin-top: 6px; display: inline-block;">Download / Open Document (.{ext})</a>',
                obj.proof_file.url,
                ext=ext
            )
        return "No proof screenshot uploaded."

    @admin.action(description="✓ APPROVE selected payments (Activate Subscriptions)")
    def approve_payments(self, request, queryset):
        approved = 0
        for payment in queryset:
            success, msg, _ = PaymentService.approve_binance_manual_payment(
                payment_id_or_obj=payment,
                admin_user=request.user,
                request=request
            )
            if success:
                approved += 1
            else:
                self.message_user(request, f"Payment #{payment.id} ({payment.transaction_id}) not approved: {msg}", level=messages.WARNING)

        if approved:
            self.message_user(request, f"Successfully approved {approved} payment(s) and activated subscription(s).", level=messages.SUCCESS)

    @admin.action(description="✕ REJECT selected payments")
    def reject_payments(self, request, queryset):
        rejected = 0
        default_reason = "Transaction reference could not be verified on Binance or was underpaid."
        for payment in queryset:
            reason = payment.rejection_reason or default_reason
            success, msg, _ = PaymentService.reject_binance_manual_payment(
                payment_id_or_obj=payment,
                admin_user=request.user,
                reason=reason,
                request=request
            )
            if success:
                rejected += 1
            else:
                self.message_user(request, f"Payment #{payment.id} not rejected: {msg}", level=messages.WARNING)

        if rejected:
            self.message_user(request, f"Marked {rejected} payment(s) as rejected.", level=messages.INFO)


@admin.register(TelebirrPayment)
class TelebirrPaymentAdmin(admin.ModelAdmin):
    """
    Dedicated Telebirr Payments administrative interface.
    Allows administrators to review customer transaction number submissions
    and approve or reject transactions with atomic subscription activation.
    """
    list_display = (
        'id',
        'user_link',
        'user_email',
        'plan_name',
        'formatted_amount',
        'transaction_id',
        'status_badge',
        'submitted_at',
        'reviewed_by',
    )
    list_filter = ('status', 'submitted_at', 'received_at')
    search_fields = (
        'transaction_id',
        'user__email',
        'user__username',
        'plan__name',
        'raw_message',
        'admin_notes',
    )
    readonly_fields = (
        'user',
        'plan',
        'subscription',
        'amount',
        'currency',
        'payment_method',
        'transaction_id',
        'received_at',
        'submitted_at',
        'verified_at',
        'reviewed_at',
        'reviewed_by',
        'original_amount',
        'discount_amount',
        'final_amount',
        'payment_country',
    )
    fieldsets = (
        ('Customer Submission', {
            'fields': (
                'user',
                'plan',
                'amount',
                'currency',
                'payment_method',
                'transaction_id',
                'submitted_at',
                'raw_message',
            )
        }),
        ('Verification & Decision', {
            'fields': (
                'status',
                'rejection_reason',
                'admin_notes',
                'reviewed_by',
                'reviewed_at',
                'verified_at',
                'subscription',
            )
        }),
        ('Pricing & Audit', {
            'classes': ('collapse',),
            'fields': (
                'payment_country',
                'original_amount',
                'discount_amount',
                'final_amount',
                'received_at',
            )
        }),
    )

    actions = ['approve_payments', 'reject_payments']

    def get_queryset(self, request):
        return super().get_queryset(request).filter(provider=Payment.PROVIDER_TELEBIRR)

    @admin.display(description="User")
    def user_link(self, obj):
        return obj.user.username if obj.user else "-"

    @admin.display(description="Email")
    def user_email(self, obj):
        return obj.user.email if obj.user else "-"

    @admin.display(description="Plan")
    def plan_name(self, obj):
        return obj.plan.name if obj.plan else "-"

    @admin.display(description="Amount")
    def formatted_amount(self, obj):
        return f"{obj.amount} {obj.currency}"

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            Payment.STATUS_PENDING: '#d97706',
            Payment.STATUS_APPROVED: '#16a34a',
            Payment.STATUS_VERIFIED: '#16a34a',
            Payment.STATUS_REJECTED: '#dc2626',
            Payment.STATUS_CANCELLED: '#6b7280',
        }
        color = colors.get(obj.status, '#374151')
        return format_html(
            '<span style="color: white; background-color: {}; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">{}</span>',
            color,
            obj.status
        )

    @admin.action(description="✓ APPROVE selected Telebirr payments (Activate Subscriptions)")
    def approve_payments(self, request, queryset):
        approved = 0
        for payment in queryset:
            success, msg, _ = PaymentService.approve_telebirr_payment(
                payment_id_or_obj=payment,
                admin_user=request.user,
                request=request
            )
            if success:
                approved += 1
            else:
                self.message_user(request, f"Payment #{payment.id} ({payment.transaction_id}) not approved: {msg}", level=messages.WARNING)

        if approved:
            self.message_user(request, f"Successfully approved {approved} Telebirr payment(s) and activated subscription(s).", level=messages.SUCCESS)

    @admin.action(description="✕ REJECT selected Telebirr payments")
    def reject_payments(self, request, queryset):
        rejected = 0
        default_reason = "Telebirr transaction number could not be verified or was underpaid."
        for payment in queryset:
            reason = payment.rejection_reason or default_reason
            success, msg, _ = PaymentService.reject_telebirr_payment(
                payment_id_or_obj=payment,
                admin_user=request.user,
                reason=reason,
                request=request
            )
            if success:
                rejected += 1
            else:
                self.message_user(request, f"Payment #{payment.id} not rejected: {msg}", level=messages.WARNING)

        if rejected:
            self.message_user(request, f"Marked {rejected} payment(s) as rejected.", level=messages.INFO)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'transaction_id',
        'provider',
        'payment_method',
        'user',
        'amount',
        'currency',
        'status',
        'plan',
        'received_at',
        'reviewed_by',
    )
    list_filter = ('payment_method', 'provider', 'status', 'currency', 'received_at')
    search_fields = (
        'transaction_id',
        'sender_identifier',
        'user__email',
        'user__username',
        'merchant_account',
        'raw_message'
    )
    readonly_fields = (
        'transaction_id',
        'merchant_trade_no',
        'prepay_id',
        'binance_order_id',
        'checkout_url',
        'qr_code_url',
        'order_expire_time',
        'provider',
        'payment_method',
        'sender_identifier',
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
        'submitted_at',
        'verified_at',
        'reviewed_at',
        'reviewed_by',
    )
    actions = ['mark_as_reviewed']

    @admin.action(description="Audit and mark selected payments as reviewed")
    def mark_as_reviewed(self, request, queryset):
        for payment in queryset:
            log_admin_action(request, 'payment_reviewed', payment.transaction_id, {
                'provider': payment.provider,
                'payment_method': payment.payment_method,
                'status': payment.status,
                'amount': str(payment.amount),
                'user': payment.user.email
            })
        self.message_user(request, f"{queryset.count()} payment(s) marked in audit trail.")
