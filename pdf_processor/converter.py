import io
import os
import shutil
import tempfile
import logging
from PIL import Image
import pymupdf
from django.conf import settings

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
    def convert(cls, input_file_path, output_file_path, dpi=None, metadata=None):
        """
        Executes conversion inside an isolated temporary directory.
        Returns dictionary with {page_count, output_size_bytes}.
        Pipeline:
        Original PDF -> Read PDF -> Render pages to images -> Process images / transparent layer
        -> Generate completely new PDF -> Apply minimal controlled metadata -> Store final PDF
        """
        configured_dpi = getattr(settings, 'PDF_RENDER_DPI', cls.DEFAULT_DPI)
        render_dpi = dpi or configured_dpi
        temp_dir = tempfile.mkdtemp(prefix="humatron_proc_")

        in_doc = None
        out_doc = None

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

                # 5. Convert composited image into final page raster image bytes
                final_rgb = composited_image.convert("RGB")
                img_buffer = io.BytesIO()
                final_rgb.save(img_buffer, format="JPEG", quality=92, optimize=True)
                img_bytes = img_buffer.getvalue()

                # Clean up intermediate PIL images and buffer immediately
                base_image.close()
                transparent_layer.close()
                composited_image.close()
                final_rgb.close()
                img_buffer.close()

                # 6. Create page matching original dimensions (in points)
                new_page = out_doc.new_page(width=rect.width, height=rect.height)
                # 7. Insert rendered raster image to completely occupy original page boundaries
                new_page.insert_image(rect, stream=img_bytes)

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
            logger.info("Successfully converted %d pages to image-based PDF: %s (%d bytes)",
                        page_count, output_file_path, output_size)

            return {
                'page_count': page_count,
                'output_size_bytes': output_size,
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
