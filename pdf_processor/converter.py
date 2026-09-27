import os
import shutil
import tempfile
import logging
import pymupdf

logger = logging.getLogger('humatron')


class PDFConversionError(Exception):
    pass


class PDFToImagePDFConverter:
    """
    High-performance, memory-efficient PDF page-to-image flattener (Sections 15, 17).
    Renders every page of input PDF as a raster image and constructs a new PDF
    preserving the exact original page dimensions while flattening all vector/text layers.
    Processes pages in a chunked/streaming loop to minimize RAM footprint.
    """

    DEFAULT_DPI = 150  # Crisp 150 DPI balance between quality and file size

    @classmethod
    def convert(cls, input_file_path, output_file_path, dpi=None):
        """
        Executes conversion inside an isolated temporary directory.
        Returns dictionary with {page_count, output_size_bytes}.
        """
        render_dpi = dpi or cls.DEFAULT_DPI
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

            # Process page by page (chunked streaming)
            for page_idx in range(page_count):
                page = in_doc[page_idx]
                rect = page.rect

                # Render page to bitmap at specified DPI
                pix = page.get_pixmap(dpi=render_dpi)
                img_bytes = pix.tobytes("jpeg")

                # Release pixmap memory immediately
                pix = None

                # Create page matching original dimensions (in points)
                new_page = out_doc.new_page(width=rect.width, height=rect.height)
                # Insert rendered image to completely occupy original page boundaries
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
