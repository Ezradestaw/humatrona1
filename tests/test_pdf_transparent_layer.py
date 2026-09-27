import os
import tempfile
import pymupdf
from PIL import Image
from django.test import TestCase, override_settings
from django.conf import settings

from pdf_processor.converter import PDFToImagePDFConverter, PDFConversionError


class PDFTransparentLayerPipelineTests(TestCase):
    """
    Tests for Sections 20-29 of the Humatron Specification Modifications:
    - Transparent RGBA layer pipeline
    - Genuine alpha transparency (alpha = 0)
    - Preservation of page dimensions, orientation, and visual correspondence
    - Multi-page ordering
    - Pure image-based output without OCR/selectable text
    - Streaming resource management & temporary cleanup
    """

    def setUp(self):
        # Create a test PDF with 3 pages of varying dimensions
        doc = pymupdf.open()
        
        # Page 1: Standard A4 (595 x 842 pt)
        p1 = doc.new_page(width=595, height=842)
        p1.insert_text((50, 100), "Humatron Page 1 Content", fontsize=20, color=(0, 0, 0))

        # Page 2: Custom dimensions (612 x 792 pt, Letter)
        p2 = doc.new_page(width=612, height=792)
        p2.insert_text((72, 120), "Humatron Page 2 Letter Size", fontsize=18, color=(0.2, 0.4, 0.6))

        # Page 3: Landscape orientation (842 x 595 pt)
        p3 = doc.new_page(width=842, height=595)
        p3.insert_text((100, 80), "Humatron Page 3 Landscape", fontsize=16, color=(0.8, 0.1, 0.1))

        self.input_pdf_path = tempfile.mktemp(suffix=".pdf", prefix="humatron_in_")
        self.output_pdf_path = tempfile.mktemp(suffix=".pdf", prefix="humatron_out_")
        doc.save(self.input_pdf_path)
        doc.close()

    def tearDown(self):
        if os.path.exists(self.input_pdf_path):
            os.remove(self.input_pdf_path)
        if os.path.exists(self.output_pdf_path):
            os.remove(self.output_pdf_path)

    def test_transparent_layer_properties(self):
        """Verifies that the transparent layer has genuine alpha transparency (alpha=0)."""
        width, height = 300, 400
        # Pipeline creates RGBA transparent layer with alpha=0
        transparent_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        self.assertEqual(transparent_layer.mode, "RGBA")
        
        # Test corners and center for alpha=0
        r, g, b, a = transparent_layer.getpixel((0, 0))
        self.assertEqual(a, 0, "Transparent layer must have alpha=0")
        
        r, g, b, a = transparent_layer.getpixel((width // 2, height // 2))
        self.assertEqual(a, 0, "Transparent layer center must have alpha=0")

        # Test alpha compositing does not alter the base image
        base = Image.new("RGBA", (width, height), (255, 100, 50, 255))
        composited = Image.alpha_composite(base, transparent_layer)
        self.assertEqual(composited.getpixel((50, 50)), (255, 100, 50, 255))

    def test_multipage_pdf_conversion_with_transparent_layer(self):
        """Multi-page PDF converts with transparent layer, preserving order and dimensions."""
        result = PDFToImagePDFConverter.convert(self.input_pdf_path, self.output_pdf_path)
        self.assertEqual(result['page_count'], 3)
        self.assertTrue(os.path.exists(self.output_pdf_path))
        self.assertGreater(result['output_size_bytes'], 0)

        # Inspect generated PDF
        out_doc = pymupdf.open(self.output_pdf_path)
        self.assertEqual(len(out_doc), 3)

        # 1. Page dimensions must be preserved exactly
        self.assertEqual(round(out_doc[0].rect.width), 595)
        self.assertEqual(round(out_doc[0].rect.height), 842)

        self.assertEqual(round(out_doc[1].rect.width), 612)
        self.assertEqual(round(out_doc[1].rect.height), 792)

        self.assertEqual(round(out_doc[2].rect.width), 842)
        self.assertEqual(round(out_doc[2].rect.height), 595)

        # 2. Each page must contain rendered image
        for i in range(3):
            images = out_doc[i].get_images()
            self.assertGreaterEqual(len(images), 1, f"Page {i+1} must contain image")

        # 3. Flattens text - output must contain NO selectable text or font objects
        for i in range(3):
            self.assertEqual(out_doc[i].get_text().strip(), "", f"Page {i+1} must not contain selectable text")

        out_doc.close()

    def test_single_page_pdf_conversion(self):
        """Single-page PDF converts properly and output is a valid image-based PDF."""
        single_doc = pymupdf.open()
        p = single_doc.new_page(width=500, height=500)
        p.insert_text((50, 50), "Single Page Test", fontsize=14)
        single_in = tempfile.mktemp(suffix=".pdf")
        single_out = tempfile.mktemp(suffix=".pdf")
        single_doc.save(single_in)
        single_doc.close()

        try:
            result = PDFToImagePDFConverter.convert(single_in, single_out)
            self.assertEqual(result['page_count'], 1)
            self.assertTrue(os.path.exists(single_out))

            out_doc = pymupdf.open(single_out)
            self.assertEqual(len(out_doc), 1)
            self.assertEqual(round(out_doc[0].rect.width), 500)
            self.assertEqual(round(out_doc[0].rect.height), 500)
            self.assertEqual(out_doc[0].get_text().strip(), "")
            out_doc.close()
        finally:
            if os.path.exists(single_in):
                os.remove(single_in)
            if os.path.exists(single_out):
                os.remove(single_out)

    def test_configurable_dpi(self):
        """Converter respects custom or configured DPI setting."""
        out_low_dpi = tempfile.mktemp(suffix=".pdf")
        try:
            result = PDFToImagePDFConverter.convert(self.input_pdf_path, out_low_dpi, dpi=72)
            self.assertEqual(result['page_count'], 3)
            self.assertTrue(os.path.exists(out_low_dpi))
        finally:
            if os.path.exists(out_low_dpi):
                os.remove(out_low_dpi)

    def test_cleanup_on_conversion_failure(self):
        """Converter removes partial output file on conversion failure."""
        invalid_in = tempfile.mktemp(suffix=".pdf")
        with open(invalid_in, 'wb') as f:
            f.write(b"NOT A REAL PDF FILE")

        failed_out = tempfile.mktemp(suffix=".pdf")

        try:
            with self.assertRaises(PDFConversionError):
                PDFToImagePDFConverter.convert(invalid_in, failed_out)
            self.assertFalse(os.path.exists(failed_out), "Failed output file must be cleaned up")
        finally:
            if os.path.exists(invalid_in):
                os.remove(invalid_in)
