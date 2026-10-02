import io
import os
import shutil
import tempfile
import logging
import numpy as np
from PIL import Image
import pymupdf
from django.conf import settings
from pdf_processor.stealth import apply_stealth_degradation
from pdf_processor.subtle_noise_ocr import (
    apply_subtle_noise,
    ocr_page,
    apply_invisible_ocr_layer,
    MAX_INVISIBLE_BYTES,
)

logger = logging.getLogger('humatron')


class PDFConversionError(Exception):
    pass


class PDFToImagePDFConverter:
    """
    High-performance, memory-efficient PDF page-to-image flattener.
    Pipeline:
    1. Read PDF: Load original PDF into memory-efficient stream.
    2. Render pages to images: Render pages at configured DPI (PDF_RENDER_DPI).
    3. Process images / transparent layer: Convert to RGBA, create genuine transparent
       layer (alpha=0), and combine via alpha_composite to flatten all vector/text layers.
    4. Generate completely new PDF: Construct a fresh, unlinked destination PDF document.
    5. Apply minimal controlled metadata: Apply strict metadata policy (no inheritance
       from source document, no user-identifying info, no dates, stripped XMP).
    6. Store final PDF: Deflate, clean garbage, and safely store verified file.

    Processes pages in a chunked/streaming loop to minimize RAM footprint.

    Security Note:
    Metadata sanitization must not be treated as a security boundary.
    Removing metadata does not prevent OCR, text extraction, remove visible document
    content, encrypt the document, guarantee anonymity, or remove every possible identifier
    from a PDF. Its purpose is specifically to minimize unnecessary document metadata.
    """

    DEFAULT_DPI = 150  # Crisp 150 DPI balance between quality and file size
    DEFAULT_PRODUCER = "Humatron PDF Processor"
    DEFAULT_TITLE = "Humatron Processed PDF"
    DEFAULT_CREATOR = "Humatron"

    # Permitted controlled metadata fields (strictly sanitized)
    ALLOWED_METADATA_KEYS = {'producer', 'title', 'creator'}

    @classmethod
    def apply_minimal_metadata(cls, doc, custom_metadata=None):
        """
        Applies controlled minimal metadata to the generated PDF document.
        Ensures the output PDF does NOT inherit or copy metadata from the original uploaded PDF.

        Metadata Policy:
        - Producer: 'Humatron PDF Processor' (preferred/required)
        - Title: 'Humatron Processed PDF' (optional controlled title)
        - Creator: 'Humatron' (optional controlled creator)
        - Strictly forbids and strips: author, subject, keywords, creationDate,
          modDate, trapped, or any user-identifying attributes (user names,
          emails, IDs, paths, timestamps, original filenames, IP addresses, etc.).
        - Removes/minimizes any XMP/XML metadata streams.
        - Neutralizes catalog /Info pointer if present.
        """
        # Determine producer, title, and creator from settings or defaults
        configured_producer = getattr(settings, 'PDF_METADATA_PRODUCER', cls.DEFAULT_PRODUCER)
        configured_title = getattr(settings, 'PDF_METADATA_TITLE', '')
        configured_creator = getattr(settings, 'PDF_METADATA_CREATOR', '')

        # Build minimal controlled metadata dictionary
        meta = {
            'producer': configured_producer or cls.DEFAULT_PRODUCER,
        }

        # Handle title if explicitly configured or provided in custom_metadata
        if configured_title:
            meta['title'] = configured_title
        elif custom_metadata and isinstance(custom_metadata, dict) and custom_metadata.get('title'):
            meta['title'] = custom_metadata['title']

        # Handle creator if explicitly configured or provided in custom_metadata
        if configured_creator:
            meta['creator'] = configured_creator
        elif custom_metadata and isinstance(custom_metadata, dict) and custom_metadata.get('creator'):
            meta['creator'] = custom_metadata['creator']

        # If custom metadata specifies a producer override, allow only if non-empty string
        if custom_metadata and isinstance(custom_metadata, dict) and custom_metadata.get('producer'):
            meta['producer'] = custom_metadata['producer']

        # Apply strictly controlled metadata
        doc.set_metadata(meta)

        # Remove/minimize XMP/XML metadata streams (Section: XMP Metadata)
        if hasattr(doc, 'del_xml_metadata'):
            try:
                doc.del_xml_metadata()
            except Exception as e:
                logger.debug("Could not delete XML metadata: %s", e)

        # Clear catalog /Info entry if present
        try:
            catalog_xref = doc.pdf_catalog()
            if "Info" in doc.xref_get_keys(catalog_xref):
                doc.xref_set_key(catalog_xref, "Info", "null")
        except Exception:
            pass

    @classmethod
    def convert(cls, input_file_path, output_file_path, dpi=None, metadata=None, stealth_config=None,
                subtle_noise=None, noise_strength=None, invisible_ocr=None):
        """
        Executes conversion inside an isolated temporary directory.
        Returns dictionary with {page_count, output_size_bytes, stealth_reports, invisible_unicode_bytes}.
        Pipeline:
        Original PDF -> Read PDF -> Render pages to images -> Process images / transparent layer
        -> Apply subtle Gaussian noise (extremely subtle)
        -> Apply OCR Stealth Degradation (SSIM budget calibrated)
        -> Generate completely new PDF -> Insert raster image
        -> Embed invisible Unicode OCR text layer (render_mode=3) with sparse ZWSP
        -> Apply minimal controlled metadata -> Store final PDF
        """
        configured_dpi = getattr(settings, 'PDF_RENDER_DPI', cls.DEFAULT_DPI)
        render_dpi = dpi or configured_dpi
        temp_dir = tempfile.mkdtemp(prefix="humatron_proc_")

        subtle_noise_enabled = getattr(settings, 'PDF_SUBTLE_NOISE_ENABLED', True) if subtle_noise is None else subtle_noise
        noise_str = getattr(settings, 'PDF_SUBTLE_NOISE_STRENGTH', 0.2) if noise_strength is None else noise_strength
        ocr_enabled = getattr(settings, 'PDF_INVISIBLE_OCR_ENABLED', False) if invisible_ocr is None else invisible_ocr

        in_doc = None
        out_doc = None
        stealth_reports = []
        total_invisible_bytes = 0

        try:
            if not os.path.exists(input_file_path):
                raise PDFConversionError(f"Input file not found: {input_file_path}")

            # Open input document
            in_doc = pymupdf.open(input_file_path)
            page_count = len(in_doc)

            if page_count == 0:
                raise PDFConversionError("Input document has 0 pages.")

            # Create destination PDF document
            out_doc = pymupdf.open()

            # Process page by page (chunked streaming for memory efficiency)
            calibrated_strength = None
            for page_idx in range(page_count):
                page = in_doc[page_idx]
                rect = page.rect

                # 1. Render page to bitmap at specified DPI
                pix = page.get_pixmap(dpi=render_dpi)

                # 2. Convert PyMuPDF pixmap to PIL RGBA image (Section 23)
                if pix.alpha:
                    base_image = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
                else:
                    base_image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")

                # Release pixmap memory immediately
                pix = None

                # 3. Create genuine transparent layer with alpha=0 (Section 21, 24)
                transparent_layer = Image.new("RGBA", base_image.size, (0, 0, 0, 0))

                # 4. Alpha composite operation combining image and transparent layer (Section 21)
                composited_image = Image.alpha_composite(base_image, transparent_layer)

                # 4.5 Apply subtle Gaussian noise before converting to PDF (extremely subtle)
                if subtle_noise_enabled and noise_str and noise_str > 0:
                    composited_rgb = apply_subtle_noise(composited_image.convert("RGB"), strength=noise_str)
                    composited_image = composited_rgb.convert("RGBA")

                # 5. Apply OCR Stealth Degradation after transparent layer
                stealth_enabled = getattr(settings, 'PDF_STEALTH_ENABLED', True) if stealth_config is None or 'enabled' not in stealth_config else stealth_config['enabled']
                if stealth_enabled:
                    # Optional back page for realistic bleed-through on multi-page docs
                    back_bgr = None
                    if page_count > 1:
                        back_page = in_doc[(page_idx + 1) % page_count]
                        back_pix = back_page.get_pixmap(dpi=render_dpi)
                        back_bgr = np.frombuffer(back_pix.samples, np.uint8).reshape(back_pix.h, back_pix.w, 3)[:, :, ::-1]
                        back_pix = None

                    rgb_array = np.array(composited_image.convert("RGB"))
                    bgr_array = rgb_array[:, :, ::-1]

                    # For multi-page efficiency: calibrate on page 0 and reuse strength on subsequent pages
                    page_cfg = dict(stealth_config or {})
                    if calibrated_strength is not None and 'strength' not in page_cfg:
                        page_cfg['strength'] = calibrated_strength

                    img_bytes, s_report = apply_stealth_degradation(
                        bgr_array,
                        back_bgr=back_bgr,
                        dpi=render_dpi,
                        page_idx=page_idx,
                        config=page_cfg,
                    )
                    if calibrated_strength is None and s_report.get('strength') is not None:
                        calibrated_strength = s_report['strength']
                    stealth_reports.append(s_report)
                    rgb_array = None
                    bgr_array = None
                    back_bgr = None
                else:
                    final_rgb = composited_image.convert("RGB")
                    img_buffer = io.BytesIO()
                    final_rgb.save(img_buffer, format="JPEG", quality=95, optimize=True)
                    img_bytes = img_buffer.getvalue()
                    final_rgb.close()
                    img_buffer.close()
                    stealth_reports.append({'enabled': False, 'page': page_idx + 1})

                # Clean up intermediate PIL images immediately
                base_image.close()
                transparent_layer.close()
                composited_image.close()

                # 6. Create page matching original dimensions (in points)
                new_page = out_doc.new_page(width=rect.width, height=rect.height)
                # 7. Insert rendered raster image to completely occupy original page boundaries
                new_page.insert_image(rect, stream=img_bytes)

                # 7.5 Apply invisible Unicode OCR text layer if enabled (render_mode=3)
                if ocr_enabled:
                    try:
                        ocr_dpi = getattr(settings, 'PDF_INVISIBLE_OCR_DPI', 200)
                        max_inv_bytes = getattr(settings, 'PDF_MAX_INVISIBLE_BYTES', MAX_INVISIBLE_BYTES)
                        ocr_data = ocr_page(page, dpi=ocr_dpi)
                        added_inv_bytes = apply_invisible_ocr_layer(
                            new_page=new_page,
                            page_rect=rect,
                            ocr_data=ocr_data,
                            total_invisible_bytes=total_invisible_bytes,
                            max_invisible_bytes=max_inv_bytes,
                        )
                        total_invisible_bytes += added_inv_bytes
                    except Exception as ocr_exc:
                        logger.warning("Optional invisible OCR text layer skipped on page %d: %s", page_idx + 1, ocr_exc)

                # Dereference image bytes
                img_bytes = None

            # Ensure parent output directory exists
            os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

            # 8. Apply minimal controlled metadata (ensures no source metadata leakage)
            cls.apply_minimal_metadata(out_doc, custom_metadata=metadata)

            # Save with maximum deflation and garbage cleanup
            temp_output = os.path.join(temp_dir, "output.pdf")
            out_doc.save(temp_output, garbage=4, deflate=True)

            # Move verified output to destination path
            shutil.move(temp_output, output_file_path)

            output_size = os.path.getsize(output_file_path)
            logger.info("Successfully converted %d pages to stealth image-based PDF: %s (%d bytes)",
                        page_count, output_file_path, output_size)

            return {
                'page_count': page_count,
                'output_size_bytes': output_size,
                'stealth_reports': stealth_reports,
                'invisible_unicode_bytes': total_invisible_bytes,
            }

        except Exception as exc:
            logger.error("PDF conversion error on %s: %s", input_file_path, exc)
            # Remove partial output if exists
            if os.path.exists(output_file_path):
                try:
                    os.remove(output_file_path)
                except OSError:
                    pass
            raise PDFConversionError(f"Conversion failed: {exc}") from exc

        finally:
            # Guarantee file handles are closed
            if in_doc and not in_doc.is_closed:
                in_doc.close()
            if out_doc and not out_doc.is_closed:
                out_doc.close()
            # Clean up isolated temporary working directory
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
