import os
import re
import pymupdf
from django.core.exceptions import ValidationError
from django.conf import settings


def sanitize_filename(filename):
    """
    Sanitizes user-provided filename by removing path traversals,
    null bytes, and illegal shell/filesystem characters.
    """
    clean_name = os.path.basename(filename or 'document.pdf')
    # Remove any non-alphanumeric, dot, underscore, dash, or space
    clean_name = re.sub(r'[^a-zA-Z0-9_\-\. ]', '_', clean_name).strip()
    if not clean_name.lower().endswith('.pdf'):
        clean_name += '.pdf'
    return clean_name[:120]


def validate_pdf_file(uploaded_file, max_size_mb=None, max_pages=None):
    """
    Comprehensive validation pipeline for untrusted PDF uploads (Section 16).
    Checks magic bytes, structure, encryption, page counts, and corruption.
    """
    default_max_size_mb = getattr(settings, 'MAX_UPLOAD_SIZE_MB', 50)
    default_max_pages = getattr(settings, 'MAX_PAGES', 200)

    effective_max_size_mb = max_size_mb or default_max_size_mb
    effective_max_pages = max_pages or default_max_pages

    # 1. Size Validation
    file_size = uploaded_file.size
    max_bytes = effective_max_size_mb * 1024 * 1024
    if file_size > max_bytes:
        raise ValidationError(
            f"File size ({file_size / (1024 * 1024):.1f} MB) exceeds maximum allowed size of {effective_max_size_mb} MB."
        )

    if file_size < 32:
        raise ValidationError("File is too small to be a valid PDF document.")

    # 2. Magic Bytes / Header Validation (Section 16)
    # Read the first 1024 bytes to inspect %PDF- header
    uploaded_file.seek(0)
    header = uploaded_file.read(1024)
    uploaded_file.seek(0)

    if b'%PDF-' not in header[:1024]:
        raise ValidationError("Invalid file format. Uploaded file lacks standard PDF header (%PDF-).")

    # 3. Structural & Integrity Validation with PyMuPDF
    try:
        # Read file into memory stream for structural inspection
        uploaded_file.seek(0)
        file_bytes = uploaded_file.read()
        uploaded_file.seek(0)

        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise ValidationError(f"The PDF file is malformed or corrupted: {exc}")

    try:
        # 4. Password / Encryption Check
        if doc.is_encrypted:
            doc.close()
            raise ValidationError("Password-protected or encrypted PDFs cannot be processed. Please decrypt first.")

        # 5. Page Count Validation
        page_count = len(doc)
        if page_count == 0:
            doc.close()
            raise ValidationError("The document contains no pages.")

        if page_count > effective_max_pages:
            doc.close()
            raise ValidationError(
                f"Document contains {page_count} pages, which exceeds the limit of {effective_max_pages} pages."
            )

        # Inspect first page dimension to check for unreadable rendering bugs
        first_page = doc[0]
        if first_page.rect.width <= 0 or first_page.rect.height <= 0:
            doc.close()
            raise ValidationError("The document has invalid page dimensions.")

    finally:
        if not doc.is_closed:
            doc.close()

    return {
        'page_count': page_count,
        'file_size': file_size,
    }
