import os
import tempfile
import numpy as np
from PIL import Image, ImageDraw
import pymupdf as fitz
from django.test import TestCase

from pdf_processor.subtle_noise_ocr import (
    add_subtle_noise,
    apply_subtle_noise,
    insert_invisible_chars,
    ocr_page,
    apply_invisible_ocr_layer,
    create_pdf,
    ZWSP,
    MAX_INVISIBLE_BYTES,
)
from pdf_processor.converter import PDFToImagePDFConverter


class SubtleNoiseAndInvisibleOCRTests(TestCase):
    """
    Automated tests verifying:
    1. Subtle Gaussian noise addition to images before PDF conversion.
    2. Visual preservation (extremely subtle, virtually identical to human eyes).
    3. Sparse zero-width space (ZWSP) insertion within max_bytes budget.
    4. Pytesseract OCR extraction of page words and bounding coordinates.
    5. Invisible text layer (render_mode=3) embedding into the final PDF.
    6. Complete integration into Humatron's PDFToImagePDFConverter.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_subtle_ocr_")

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_sample_pdf(self, path):
        """Helper creating a standard test PDF with legible text."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Humatron Secure Document Converter", fontsize=20)
        page.insert_text((72, 140), "This is a confidential report with multiple words for OCR testing.", fontsize=14)
        page.insert_text((72, 180), "Subtle Gaussian noise and invisible Unicode characters are verified.", fontsize=12)
        doc.save(path)
        doc.close()

    def test_add_subtle_noise_preserves_dimensions_and_valid_range(self):
        """Gaussian noise is applied, pixel values stay in [0, 255], and visuals are preserved."""
        in_img_path = os.path.join(self.temp_dir, "test_input.jpg")
        out_img_path = os.path.join(self.temp_dir, "test_output.jpg")

        # Create 200x200 RGB test image
        img = Image.new("RGB", (200, 200), color=(180, 190, 200))
        img.save(in_img_path, quality=100)

        # Apply subtle noise (extremely subtle strength=0.2)
        add_subtle_noise(in_img_path, out_img_path, strength=0.2)
        self.assertTrue(os.path.exists(out_img_path))

        out_img = Image.open(out_img_path)
        self.assertEqual(out_img.size, (200, 200))

        arr_in = np.asarray(Image.open(in_img_path)).astype(np.float32)
        arr_out = np.asarray(out_img).astype(np.float32)

        # Pixels must remain in valid 0..255 range
        self.assertTrue(np.all(arr_out >= 0))
        self.assertTrue(np.all(arr_out <= 255))

        # Visual difference must be extremely subtle (mean diff < 1.0 intensity step)
        mean_diff = float(np.mean(np.abs(arr_in - arr_out)))
        self.assertLess(mean_diff, 1.0, "Extremely subtle noise should have mean difference < 1.0")

    def test_insert_invisible_chars_respects_budget_and_sparsity(self):
        """ZWSP characters are inserted sparsely (every ~10 words) and respect max_bytes."""
        text = "word " * 35
        text = text.strip()

        # Generous budget
        res = insert_invisible_chars(text, max_bytes=1000, step=10)
        zwsp_count = res.count(ZWSP)
        self.assertEqual(zwsp_count, 3, "In 35 words, insertions at index 10, 20, 30 yield 3 ZWSPs.")

        # Zero or insufficient budget
        res_zero = insert_invisible_chars(text, max_bytes=2, step=10)
        self.assertEqual(res_zero.count(ZWSP), 0, "No ZWSP should be inserted if budget is below char_bytes.")

        # Exact budget for 1 ZWSP (3 bytes)
        res_one = insert_invisible_chars(text, max_bytes=3, step=10)
        self.assertEqual(res_one.count(ZWSP), 1)

    def test_ocr_page_extracts_words_and_coordinates(self):
        """ocr_page renders the page and extracts text with bounding boxes via pytesseract."""
        pdf_path = os.path.join(self.temp_dir, "ocr_test.pdf")
        self._create_sample_pdf(pdf_path)

        doc = fitz.open(pdf_path)
        data = ocr_page(doc[0], dpi=200)
        doc.close()

        extracted_words = [w.strip() for w in data.get("text", []) if w.strip()]
        self.assertIn("Humatron", extracted_words)
        self.assertIn("Secure", extracted_words)
        self.assertGreater(len(data.get("left", [])), 0)
        self.assertGreater(len(data.get("width", [])), 0)

    def test_create_pdf_produces_invisible_text_and_clean_visuals(self):
        """create_pdf produces output with subtle noise, invisible text layer, and pristine visuals."""
        in_pdf = os.path.join(self.temp_dir, "input.pdf")
        out_pdf = os.path.join(self.temp_dir, "output.pdf")
        self._create_sample_pdf(in_pdf)

        bytes_added = create_pdf(in_pdf, out_pdf, noise_strength=0.2, ocr_dpi=200)
        self.assertTrue(os.path.exists(out_pdf))
        self.assertGreater(bytes_added, 0)

        # Inspect output document
        out_doc = fitz.open(out_pdf)
        self.assertEqual(len(out_doc), 1)
        out_page = out_doc[0]

        # 1. Visual appearance check: render_mode=3 produces no visible ink
        in_doc = fitz.open(in_pdf)
        pix_in = in_doc[0].get_pixmap()
        pix_out = out_page.get_pixmap()
        in_doc.close()

        arr_in = np.frombuffer(pix_in.samples, np.uint8).astype(float)
        arr_out = np.frombuffer(pix_out.samples, np.uint8).astype(float)
        mean_diff = float(np.mean(np.abs(arr_in - arr_out)))
        self.assertLess(mean_diff, 1.5, "Visual appearance must be approximately normal to visual inspection.")

        # 2. Text layer check: extracted text must contain OCR words and literal ZWSP
        extracted = out_page.get_text()
        self.assertIn("Humatron", extracted)
        self.assertIn(ZWSP, extracted)

        out_doc.close()

    def test_converter_integration_with_invisible_ocr(self):
        """PDFToImagePDFConverter supports subtle_noise and invisible_ocr seamlessly."""
        in_pdf = os.path.join(self.temp_dir, "conv_in.pdf")
        out_pdf = os.path.join(self.temp_dir, "conv_out.pdf")
        self._create_sample_pdf(in_pdf)

        res = PDFToImagePDFConverter.convert(
            in_pdf,
            out_pdf,
            subtle_noise=True,
            noise_strength=0.2,
            invisible_ocr=True,
        )

        self.assertEqual(res['page_count'], 1)
        self.assertGreater(res['invisible_unicode_bytes'], 0)
        self.assertTrue(os.path.exists(out_pdf))

        doc = fitz.open(out_pdf)
        text = doc[0].get_text()
        self.assertIn("Humatron", text)
        self.assertIn(ZWSP, text)
        doc.close()
