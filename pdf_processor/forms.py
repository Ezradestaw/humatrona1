from django import forms
from django.core.exceptions import ValidationError
from .validators import validate_pdf_file, sanitize_filename
from subscriptions.services import SubscriptionService


class PDFUploadForm(forms.Form):
    pdf_file = forms.FileField(
        label="Select PDF Document",
        widget=forms.FileInput(attrs={
            'class': 'form-input-file',
            'accept': '.pdf,application/pdf',
            'id': 'id_pdf_file',
        }),
        help_text="Standard PDF file (.pdf)"
    )


    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def clean_pdf_file(self):
        uploaded_file = self.cleaned_data.get('pdf_file')
        if not uploaded_file:
            raise ValidationError("Please select a file to upload.")

        # Check preliminary authorization
        allowed, msg, is_trial, max_size_mb, max_pages = SubscriptionService.can_process_pdf(
            self.user,
            file_size_bytes=uploaded_file.size,
            page_count=1
        )
        if not allowed:
            raise ValidationError(msg)

        # Validate file structure, encryption, header, and page limits
        metadata = validate_pdf_file(uploaded_file, max_size_mb=max_size_mb, max_pages=max_pages)

        # Re-check authorization with exact page count
        allowed_full, msg_full, _, _, _ = SubscriptionService.can_process_pdf(
            self.user,
            file_size_bytes=uploaded_file.size,
            page_count=metadata['page_count']
        )
        if not allowed_full:
            raise ValidationError(msg_full)

        self.cleaned_data['page_count'] = metadata['page_count']
        self.cleaned_data['file_size'] = metadata['file_size']
        self.cleaned_data['clean_filename'] = sanitize_filename(uploaded_file.name)

        return uploaded_file
