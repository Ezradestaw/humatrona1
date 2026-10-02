import logging
from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver
from .models import PDFProcessingJob

logger = logging.getLogger('humatron')


@receiver(user_logged_out)
def purge_session_pdfs_on_logout(sender, request, user, **kwargs):
    """
    Purges processed and uploaded PDF files from disk when the user's session ends.
    Ensures no processed PDF persists on disk after the user session terminates.
    """
    if not request:
        return

    session_key = getattr(request, 'session', None) and request.session.session_key
    job_ids = getattr(request, 'session', None) and request.session.get('pdf_job_ids', [])

    jobs_purged = 0
    jobs_qs = PDFProcessingJob.objects.filter(is_files_deleted=False)

    if session_key:
        for job in jobs_qs.filter(session_key=session_key):
            job.purge_files()
            jobs_purged += 1

    if job_ids:
        for job in jobs_qs.filter(id__in=job_ids):
            if not job.is_files_deleted:
                job.purge_files()
                jobs_purged += 1

    if user and getattr(user, 'is_authenticated', False):
        for job in jobs_qs.filter(user=user):
            if not job.is_files_deleted:
                job.purge_files()
                jobs_purged += 1

    if jobs_purged > 0:
        logger.info(
            "Purged %d PDF file(s) on session logout for user %s",
            jobs_purged,
            getattr(user, 'email', 'anonymous')
        )
