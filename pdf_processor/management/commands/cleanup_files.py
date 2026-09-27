from django.core.management.base import BaseCommand
from pdf_processor.tasks import cleanup_expired_files_task


class Command(BaseCommand):
    help = "Cleans up expired uploaded and processed PDF documents (Section 20)."

    def handle(self, *args, **options):
        result = cleanup_expired_files_task()
        self.stdout.write(self.style.SUCCESS(f"File cleanup executed: {result}"))
