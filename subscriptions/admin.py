from django.contrib import admin
from .models import SubscriptionPlan, Subscription
from audit.services import log_admin_action


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'code',
        'price',
        'currency',
        'price_etb',
        'duration_days',
        'pdf_limit',
        'max_file_size_mb',
        'active',
        'sort_order',
    )
    list_filter = ('active', 'currency')
    search_fields = ('name', 'code', 'description')
    prepopulated_fields = {'code': ('name',)}
    list_editable = ('price', 'price_etb', 'pdf_limit', 'max_file_size_mb', 'active', 'sort_order')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        action_name = 'plan_modified' if change else 'plan_created'
        log_admin_action(request, 'plan_modified', obj.code, {
            'plan_name': obj.name,
            'price': str(obj.price),
            'price_etb': str(obj.price_etb),
            'pdf_limit': obj.pdf_limit,
            'active': obj.active
        })


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'plan',
        'status',
        'used_count',
        'pdf_limit',
        'start_date',
        'end_date',
        'payment_method',
    )
    list_filter = ('status', 'plan', 'payment_method', 'created_at')
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'payment_method')
    readonly_fields = ('created_at', 'updated_at')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change:
            log_admin_action(request, 'subscription_changed', str(obj.id), {
                'user': obj.user.email,
                'status': obj.status,
                'used_count': obj.used_count,
                'pdf_limit': obj.pdf_limit
            })
