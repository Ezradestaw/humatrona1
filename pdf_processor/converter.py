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
    High-performance, memory-efficient PDF page-to-image flattener (Sections 20-29).
    Pipeline:
    1. Render each page of input PDF as a raster bitmap at configured DPI.
    2. Convert bitmap to PIL RGBA image.
    3. Create a genuine transparent RGBA layer (alpha = 0).
    4. Combine image and transparent layer via alpha_composite operation.
    5. Construct a new PDF page preserving the exact original page dimensions.
    6. Flatten all vector, font, and text layers into pure image pixels.
    Processes pages in a chunked/streaming loop to minimize RAM footprint.
    """

    DEFAULT_DPI = 150  # Crisp 150 DPI balance between quality and file size

    @classmethod
    def convert(cls, input_file_path, output_file_path, dpi=None):
        """
        Executes conversion inside an isolated temporary directory.
        Returns dictionary with {page_count, output_size_bytes}.
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
