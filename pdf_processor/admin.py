import os
from django.conf import settings
from django.contrib import admin
from .models import PDFProcessingJob
from audit.services import log_admin_action


@admin.register(PDFProcessingJob)
class PDFProcessingJobAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'original_filename',
        'page_count',
        'status',
        'download_count',
        'is_files_deleted',
        'created_at',
        'completed_at',
    )
    list_filter = ('status', 'is_files_deleted', 'created_at')
    search_fields = ('id', 'user__email', 'original_filename', 'stored_filename')
    readonly_fields = (
        'id',
        'user',
        'original_filename',
        'stored_filename',
        'processed_filename',
        'page_count',
        'input_size',
        'output_size',
        'status',
        'error_message',
        'download_count',
        'file_expires_at',
        'is_files_deleted',
        'created_at',
        'started_at',
        'completed_at',
    )

    actions = ['force_delete_files']

    @admin.action(description="Securely purge and delete files for selected jobs")
    def force_delete_files(self, request, queryset):
        deleted_count = 0
        for job in queryset:
            input_path = os.path.join(settings.MEDIA_ROOT, 'uploads', job.stored_filename)
            if os.path.exists(input_path):
                try:
                    os.remove(input_path)
                except OSError:
                    pass

            if job.processed_filename:
                output_path = os.path.join(settings.MEDIA_ROOT, 'processed', job.processed_filename)
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except OSError:
                        pass

            job.is_files_deleted = True
            job.status = PDFProcessingJob.STATUS_EXPIRED
            job.save(update_fields=['is_files_deleted', 'status'])
            deleted_count += 1

            log_admin_action(request, 'document_deleted', str(job.id), {
                'user': job.user.email,
                'original_filename': job.original_filename
            })

        self.message_user(request, f"Files purged for {deleted_count} jobs and recorded in audit log.")
