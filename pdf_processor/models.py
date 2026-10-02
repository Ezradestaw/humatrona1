import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class PDFProcessingJob(models.Model):
    """
    Tracks PDF conversion jobs (Sections 18, 19, 20).
    Uses non-guessable UUIDs and stores files safely with random filenames.
    """
    STATUS_QUEUED = 'QUEUED'
    STATUS_PROCESSING = 'PROCESSING'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_FAILED = 'FAILED'
    STATUS_EXPIRED = 'EXPIRED'

    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_EXPIRED, 'Expired / Deleted'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pdf_jobs'
    )
    original_filename = models.CharField(max_length=255)
    stored_filename = models.CharField(max_length=255, help_text="Randomized server filename in uploads/")
    processed_filename = models.CharField(max_length=255, blank=True, help_text="Randomized server filename in processed/")
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_QUEUED,
        db_index=True
    )
    page_count = models.PositiveIntegerField(default=0)
    input_size = models.PositiveIntegerField(default=0, help_text="Input file size in bytes")
    output_size = models.PositiveIntegerField(default=0, help_text="Output file size in bytes")
    error_message = models.TextField(blank=True)
    download_count = models.PositiveIntegerField(default=0)
    
    file_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    is_files_deleted = models.BooleanField(default=False)
    session_key = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Session key during which the PDF was uploaded/processed"
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['file_expires_at']),
            models.Index(fields=['session_key']),
        ]

    def purge_files(self):
        """
        Securely removes the uploaded source PDF and processed output PDF from disk.
        Sets is_files_deleted = True and marks status as EXPIRED.
        """
        import os
        from django.conf import settings

        # 1. Remove input upload file
        if self.stored_filename:
            input_path = os.path.join(settings.MEDIA_ROOT, 'uploads', self.stored_filename)
            if os.path.exists(input_path):
                try:
                    os.remove(input_path)
                except OSError:
                    pass

        # 2. Remove processed output file
        if self.processed_filename:
            output_path = os.path.join(settings.MEDIA_ROOT, 'processed', self.processed_filename)
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass

        self.is_files_deleted = True
        if self.status == self.STATUS_COMPLETED:
            self.status = self.STATUS_EXPIRED
        self.save(update_fields=['is_files_deleted', 'status'])

    def __str__(self):
        return f"Job {self.id} ({self.original_filename}) - {self.status}"

    @property
    def is_downloadable(self):
        return self.status == self.STATUS_COMPLETED and not self.is_files_deleted and bool(self.processed_filename)

    @property
    def input_size_formatted(self):
        if self.input_size >= 1024 * 1024:
            return f"{self.input_size / (1024 * 1024):.1f} MB"
        return f"{self.input_size / 1024:.1f} KB"

    @property
    def output_size_formatted(self):
        if self.output_size >= 1024 * 1024:
            return f"{self.output_size / (1024 * 1024):.1f} MB"
        return f"{self.output_size / 1024:.1f} KB"
