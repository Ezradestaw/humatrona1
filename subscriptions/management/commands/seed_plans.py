from django.core.management.base import BaseCommand
from subscriptions.models import SubscriptionPlan


class Command(BaseCommand):
    help = "Seeds or updates the four PDF Stealth subscription plans."

    def handle(self, *args, **options):
        plans_data = [
            {
                'name': 'Free',
                'code': 'free',
                'slug': 'free',
                'description': 'Get started with 5 PDF Stealth processes per month at no cost.',
                'price': 0.00,
                'currency': 'USD',
                'price_etb': 0.00,
                'duration_days': 30,
                'usage_limit': 5,
                'max_file_size': 10,
                'processing_priority': 'Standard',
                'active': True,
                'sort_order': 1,
            },
            {
                'name': 'Basic',
                'code': 'basic',
                'slug': 'basic',
                'description': 'For regular users who need frequent PDF Stealth processing.',
                'price': 18.00,
                'currency': 'USD',
                'price_etb': 400.00,
                'duration_days': 30,
                'usage_limit': 50,
                'max_file_size': 50,
                'processing_priority': 'Higher than Free',
                'active': True,
                'sort_order': 2,
            },
            {
                'name': 'Pro',
                'code': 'pro',
                'slug': 'pro',
                'description': 'Priority PDF Stealth processing for professionals with high volume needs.',
                'price': 48.00,
                'currency': 'USD',
                'price_etb': 600.00,
                'duration_days': 30,
                'usage_limit': 200,
                'max_file_size': 100,
                'processing_priority': 'Priority',
                'active': True,
                'sort_order': 3,
            },
            {
                'name': 'Unlimited',
                'code': 'unlimited',
                'slug': 'unlimited',
                'description': 'Highest priority PDF Stealth processing with unlimited documents and maximum file size.',
                'price': 90.00,
                'currency': 'USD',
                'price_etb': 1000.00,
                'duration_days': 30,
                'usage_limit': 0,  # 0 = unlimited (fair-use policy applies)
                'max_file_size': 250,
                'processing_priority': 'Highest',
                'active': True,
                'sort_order': 4,
            },
        ]

        created_count = 0
        for data in plans_data:
            plan, created = SubscriptionPlan.objects.update_or_create(
                slug=data['slug'],
                defaults=data
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"Created plan: {plan.name}"))
            else:
                self.stdout.write(f"Updated plan: {plan.name} (${plan.price} / {plan.price_etb} ETB)")

        self.stdout.write(self.style.SUCCESS(f"Seed complete. {created_count} plans created."))
