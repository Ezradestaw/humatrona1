from decimal import Decimal
from django.db import migrations


def set_telebirr_plan_prices(apps, schema_editor):
    SubscriptionPlan = apps.get_model('subscriptions', 'SubscriptionPlan')

    etb_prices = {
        'free': Decimal('0.00'),
        'basic': Decimal('200.00'),
        'pro': Decimal('300.00'),
        'unlimited': Decimal('500.00'),
    }

    for slug, price_etb in etb_prices.items():
        SubscriptionPlan.objects.filter(slug=slug).update(price_etb=price_etb)


def reverse_telebirr_plan_prices(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0004_seed_four_subscription_plans'),
    ]

    operations = [
        migrations.RunPython(set_telebirr_plan_prices, reverse_telebirr_plan_prices),
    ]
