import os
from datetime import timedelta
import logging
from celery import shared_task
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import PDFProcessingJob
from .converter import PDFToImagePDFConverter, PDFConversionError
from usage.services import UsageService
from notifications.services import EmailService

logger = logging.getLogger('humatron')


@shared_task(bind=True, max_retries=1)
def process_pdf_job_task(self, job_id):
    """
    Background worker task for asynchronous PDF conversion (Sections 15, 51, 52).
    """
    try:
        job = PDFProcessingJob.objects.get(id=job_id)
    except PDFProcessingJob.DoesNotExist:
        logger.error("Job %s does not exist.", job_id)
        return "Job not found"

    job.status = PDFProcessingJob.STATUS_PROCESSING
    job.started_at = timezone.now()
    job.save(update_fields=['status', 'started_at'])

    input_path = os.path.join(settings.MEDIA_ROOT, 'uploads', job.stored_filename)
    output_filename = f"processed_{job.id}.pdf"
    output_path = os.path.join(settings.MEDIA_ROOT, 'processed', output_filename)

    try:
        result = PDFToImagePDFConverter.convert(input_path, output_path)

        now = timezone.now()
        retention_days = getattr(settings, 'FILE_RETENTION_DAYS', 7)
        expires_at = now + timedelta(days=retention_days)

        job.status = PDFProcessingJob.STATUS_COMPLETED
        job.processed_filename = output_filename
        job.page_count = result['page_count']
        job.output_size = result['output_size_bytes']
        job.completed_at = now
        job.file_expires_at = expires_at
        job.save(update_fields=[
            'status', 'processed_filename', 'page_count',
            'output_size', 'completed_at', 'file_expires_at'
        ])

        # Idempotently record usage (Section 25)
        UsageService.record_job_usage(job)

        # Send completion email
        domain = getattr(settings, 'SITE_DOMAIN', 'humatron.me')
        download_url = f"https://{domain}{reverse('pdf_processor:download', kwargs={'job_id': str(job.id)})}"
        EmailService.send_pdf_completed_email(job.user, job, download_url)

        logger.info("PDF job %s completed successfully.", job.id)
        return f"Job {job.id} completed"

    except Exception as exc:
        job.status = PDFProcessingJob.STATUS_FAILED
        job.error_message = str(exc)
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'error_message', 'completed_at'])

        # Notify user of failure
        EmailService.send_pdf_failed_email(job.user, job, str(exc))
        logger.error("PDF job %s failed: %s", job.id, exc)
        return f"Job {job.id} failed: {exc}"


@shared_task
def cleanup_expired_files_task():
    """
    Section 20: Automatic file retention cleanup.
    Deletes files older than FILE_RETENTION_DAYS while preserving database accounting history.
    """
    now = timezone.now()
    expired_jobs = PDFProcessingJob.objects.filter(
        file_expires_at__lte=now,
        is_files_deleted=False
    )
    cleaned_count = 0

    for job in expired_jobs:
        # 1. Delete upload input file
        input_path = os.path.join(settings.MEDIA_ROOT, 'uploads', job.stored_filename)
        if os.path.exists(input_path):
            try:
                os.remove(input_path)
            except OSError as e:
                logger.warning("Error deleting uploaded file %s: %s", input_path, e)

        # 2. Delete processed output file
        if job.processed_filename:
            output_path = os.path.join(settings.MEDIA_ROOT, 'processed', job.processed_filename)
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError as e:
                    logger.warning("Error deleting processed file %s: %s", output_path, e)

        job.is_files_deleted = True
        job.status = PDFProcessingJob.STATUS_EXPIRED
        job.save(update_fields=['is_files_deleted', 'status'])
        cleaned_count += 1

    logger.info("Cleanup completed: removed files for %d expired jobs.", cleaned_count)
    return f"Cleaned up {cleaned_count} jobs."
