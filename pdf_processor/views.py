import os
import uuid
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse

from .forms import PDFUploadForm
from .models import PDFProcessingJob
from .tasks import process_pdf_job_task
from subscriptions.services import SubscriptionService


@login_required
def upload_view(request):
    """
    Handles PDF document uploads with strict validation and quota enforcement.
    """
    user = request.user
    allowed, msg, is_trial, max_size_mb, max_pages = SubscriptionService.can_process_pdf(user)

    if not allowed and request.method == 'GET':
        messages.warning(request, msg)

    if request.method == 'POST':
        form = PDFUploadForm(request.POST, request.FILES, user=user)
        if form.is_valid():
            uploaded_file = form.cleaned_data['pdf_file']
            clean_filename = form.cleaned_data['clean_filename']
            page_count = form.cleaned_data['page_count']
            file_size = form.cleaned_data['file_size']

            # Generate non-guessable random server filename (Section 17)
            random_filename = f"{uuid.uuid4().hex}.pdf"
            upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
            os.makedirs(upload_dir, exist_ok=True)
            stored_path = os.path.join(upload_dir, random_filename)

            # Write file in chunks to minimize memory usage
            with open(stored_path, 'wb+') as destination:
                for chunk in uploaded_file.chunks():
                    destination.write(chunk)

            # Create job record
            job = PDFProcessingJob.objects.create(
                user=user,
                original_filename=clean_filename,
                stored_filename=random_filename,
                page_count=page_count,
                input_size=file_size,
                status=PDFProcessingJob.STATUS_QUEUED
            )

            # Process the PDF document reliably:
            # If CELERY_TASK_ALWAYS_EAGER (default) or if Celery worker is offline, process synchronously
            if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', True):
                process_pdf_job_task.apply(args=[str(job.id)])
            else:
                try:
                    process_pdf_job_task.delay(str(job.id))
                except Exception as task_err:
                    logger.warning("Celery dispatch error (%s); processing inline directly", task_err)
                    process_pdf_job_task.apply(args=[str(job.id)])

            job.refresh_from_db()
            if job.status == PDFProcessingJob.STATUS_COMPLETED:
                messages.success(request, "Document processed successfully! Click the download button below.")
            elif job.status == PDFProcessingJob.STATUS_FAILED:
                messages.error(request, f"Processing failed: {job.error_message}")
            else:
                messages.info(request, "File uploaded successfully. Processing started.")

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'job_id': str(job.id),
                    'status_url': reverse('pdf_processor:job_detail', kwargs={'job_id': str(job.id)})
                })

            return redirect('pdf_processor:job_detail', job_id=str(job.id))

        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                errors = [str(err) for err_list in form.errors.values() for err in err_list]
                return JsonResponse({'success': False, 'errors': errors}, status=400)
    else:
        form = PDFUploadForm(user=user)

    context = {
        'form': form,
        'allowed': allowed,
        'reason': msg,
        'is_trial': is_trial,
        'max_size_mb': max_size_mb,
        'max_pages': max_pages,
    }
    return render(request, 'pdf_processor/upload.html', context)


@login_required
def job_detail_view(request, job_id):
    """
    Job status and progress tracking view.
    Includes JSON endpoint for frontend polling.
    """
    job = get_object_or_404(PDFProcessingJob, id=job_id, user=request.user)

    # Return JSON for background polling
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
        download_url = reverse('pdf_processor:download', kwargs={'job_id': str(job.id)}) if job.is_downloadable else None
        return JsonResponse({
            'id': str(job.id),
            'status': job.status,
            'is_downloadable': job.is_downloadable,
            'download_url': download_url,
            'error_message': job.error_message,
            'page_count': job.page_count,
            'output_size_formatted': job.output_size_formatted,
        })

    return render(request, 'pdf_processor/job_detail.html', {'job': job})


@login_required
def download_view(request, job_id):
    """
    Section 19: Secure authenticated document download.
    Strict object authorization: verifies job belongs to requesting user.
    Never exposes internal filesystem paths or permanent public URLs.
    """
    job = get_object_or_404(PDFProcessingJob, id=job_id, user=request.user)

    if not job.is_downloadable:
        if job.is_files_deleted:
            raise Http404("This document has expired and been deleted in accordance with retention policy.")
        raise Http404("File is not ready for download or processing failed.")

    file_path = os.path.join(settings.MEDIA_ROOT, 'processed', job.processed_filename)
    if not os.path.exists(file_path):
        raise Http404("Requested file does not exist on disk.")

    job.download_count += 1
    job.save(update_fields=['download_count'])

    # Format attachment filename based on original document name
    base_name = os.path.splitext(job.original_filename)[0]
    download_filename = f"{base_name}_humatron_flattened.pdf"

    response = FileResponse(open(file_path, 'rb'), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{download_filename}"'
    return response


@login_required
def job_list_view(request):
    """PDF processing history for the authenticated user."""
    jobs = PDFProcessingJob.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'pdf_processor/job_list.html', {'jobs': jobs})


@login_required
def job_delete_view(request, job_id):
    """Allows user to remove a completed/failed job and delete server files."""
    job = get_object_or_404(PDFProcessingJob, id=job_id, user=request.user)

    if request.method == 'POST':
        # Remove files from disk
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

        job.delete()
        messages.success(request, "Document record and server files removed.")
        return redirect('pdf_processor:history')

    return render(request, 'pdf_processor/confirm_delete.html', {'job': job})
