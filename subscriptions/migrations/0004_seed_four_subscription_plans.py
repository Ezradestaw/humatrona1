from decimal import Decimal
from django.db import migrations


def seed_subscription_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model('subscriptions', 'SubscriptionPlan')

    plans_data = [
        {
            'name': 'Free',
            'slug': 'free',
            'code': 'free',
            'price': Decimal('0.00'),
            'currency': 'USD',
            'billing_period': 'month',
            'usage_limit': 5,
            'max_file_size': 10,
            'processing_priority': 'Normal',
            'description': 'Basic PDF conversion for casual users.',
            'features': [
                '5 PDFs/month',
                '10 MB maximum file size',
                'Standard processing',
                'Normal priority'
            ],
            'active': True,
            'sort_order': 1,
            'price_etb': Decimal('0.00'),
        },
        {
            'name': 'Basic',
            'slug': 'basic',
            'code': 'basic',
            'price': Decimal('9.00'),
            'currency': 'USD',
            'billing_period': 'month',
            'usage_limit': 50,
            'max_file_size': 50,
            'processing_priority': 'Higher than Free',
            'description': 'Ideal for regular individual document processing.',
            'features': [
                '50 PDFs/month',
                '50 MB maximum file size',
                'Faster processing',
                'Higher priority than Free'
            ],
            'active': True,
            'sort_order': 2,
            'price_etb': Decimal('200.00'),
        },
        {
            'name': 'Pro',
            'slug': 'pro',
            'code': 'pro',
            'price': Decimal('24.00'),
            'currency': 'USD',
            'billing_period': 'month',
            'usage_limit': 200,
            'max_file_size': 100,
            'processing_priority': 'High',
            'description': 'Priority processing for professionals and busy teams.',
            'features': [
                '200 PDFs/month',
                '100 MB maximum file size',
                'Priority processing',
                'High priority'
            ],
            'active': True,
            'sort_order': 3,
            'price_etb': Decimal('300.00'),
        },
        {
            'name': 'Unlimited',
            'slug': 'unlimited',
            'code': 'unlimited',
            'price': Decimal('45.00'),
            'currency': 'USD',
            'billing_period': 'month',
            'usage_limit': 0,
            'max_file_size': 250,
            'processing_priority': 'Highest',
            'description': 'Unlimited processing with maximum performance and server priority.',
            'features': [
                'Unlimited processing',
                '250 MB maximum file size',
                'Highest processing priority',
                'Server fair-use protection'
            ],
            'active': True,
            'sort_order': 4,
            'price_etb': Decimal('500.00'),
        },
    ]

    for plan in plans_data:
        SubscriptionPlan.objects.update_or_create(
            slug=plan['slug'],
            defaults=plan
        )

    # Deactivate legacy plans
    valid_slugs = [p['slug'] for p in plans_data]
    SubscriptionPlan.objects.exclude(slug__in=valid_slugs).update(active=False)


def reverse_seed_subscription_plans(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0003_remove_subscription_discount_percentage_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_subscription_plans, reverse_seed_subscription_plans),
    ]
