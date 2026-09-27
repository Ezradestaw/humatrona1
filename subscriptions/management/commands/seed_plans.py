from django.core.management.base import BaseCommand
from subscriptions.models import SubscriptionPlan


class Command(BaseCommand):
    help = "Seeds the initial four subscription plans (Section 21)."

    def handle(self, *args, **options):
        plans_data = [
            {
                'name': 'Starter',
                'code': 'starter',
                'description': 'Ideal for individual professionals with occasional PDF conversion requirements.',
                'price': 20.00,
                'currency': 'USD',
                'price_etb': 2700.00,
                'duration_days': 30,
                'pdf_limit': 10,
                'max_file_size_mb': 25,
                'max_pages_per_pdf': 100,
                'active': True,
                'sort_order': 1,
            },
            {
                'name': 'Professional',
                'code': 'professional',
                'description': 'Recommended primary plan for regular high-quality PDF flattening and processing.',
                'price': 50.00,
                'currency': 'USD',
                'price_etb': 6750.00,
                'duration_days': 30,
                'pdf_limit': 25,
                'max_file_size_mb': 50,
                'max_pages_per_pdf': 200,
                'active': True,
                'sort_order': 2,
            },
            {
                'name': 'Business',
                'code': 'business',
                'description': 'Expanded processing capacity for demanding document teams and offices.',
                'price': 100.00,
                'currency': 'USD',
                'price_etb': 13500.00,
                'duration_days': 30,
                'pdf_limit': 60,
                'max_file_size_mb': 100,
                'max_pages_per_pdf': 350,
                'active': True,
                'sort_order': 3,
            },
            {
                'name': 'Enterprise',
                'code': 'enterprise',
                'description': 'Maximum volume and priority background worker throughput for heavy workflows.',
                'price': 250.00,
                'currency': 'USD',
                'price_etb': 33750.00,
                'duration_days': 30,
                'pdf_limit': 200,
                'max_file_size_mb': 200,
                'max_pages_per_pdf': 600,
                'active': True,
                'sort_order': 4,
            },
        ]

        created_count = 0
        for data in plans_data:
            plan, created = SubscriptionPlan.objects.update_or_create(
                code=data['code'],
                defaults=data
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"Created plan: {plan.name}"))
            else:
                self.stdout.write(f"Updated plan: {plan.name}")

        self.stdout.write(self.style.SUCCESS(f"Seed complete. {created_count} plans created."))
