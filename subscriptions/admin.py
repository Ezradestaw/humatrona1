from django.contrib import admin
from .models import SubscriptionPlan, Subscription
from audit.services import log_admin_action


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'slug',
        'price',
        'currency',
        'billing_period',
        'usage_limit',
        'max_file_size',
        'processing_priority',
        'active',
        'sort_order',
    )
    list_filter = ('active', 'currency', 'processing_priority', 'billing_period')
    search_fields = ('name', 'slug', 'description')
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ('price', 'usage_limit', 'max_file_size', 'processing_priority', 'active', 'sort_order')
    
    fieldsets = (
        ('General Information', {
            'fields': ('name', 'slug', 'description', 'sort_order', 'active')
        }),
        ('Pricing & Billing', {
            'fields': ('price', 'currency', 'billing_period', 'price_etb', 'duration_days')
        }),
        ('Capacity & Performance Limits', {
            'fields': ('usage_limit', 'max_file_size', 'processing_priority', 'features')
        }),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        log_admin_action(request, 'plan_modified' if change else 'plan_created', obj.slug, {
            'plan_name': obj.name,
            'price': str(obj.price),
            'usage_limit': obj.usage_limit,
            'max_file_size': obj.max_file_size,
            'processing_priority': obj.processing_priority,
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
