import os
import tempfile
import numpy as np
import pymupdf
from django.test import TestCase
from pdf_processor.converter import PDFToImagePDFConverter
from pdf_processor.stealth import ssim


class PDFVisualFidelityTests(TestCase):
    """
    Automated verification of visual fidelity between input and output PDFs.
    Validates:
    - Page count preservation
    - Page dimensions (width, height in points)
    - Orientation (portrait, landscape, different sizes)
    - Visual similarity via SSIM >= 0.990
    - Text positioning, tables, lines, and colored graphics
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="fidelity_test_")
        self.input_pdf = os.path.join(self.temp_dir, "input.pdf")
        self.output_pdf = os.path.join(self.temp_dir, "output.pdf")

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_multi_page_multi_orientation_visual_fidelity(self):
        """Validates that a multi-page document with portrait and landscape preserves geometry and visual fidelity."""
        doc = pymupdf.open()

        # Page 1: A4 Portrait (595 x 842 pt)
        p1 = doc.new_page(width=595, height=842)
        p1.insert_text((50, 40), "TEST HEADER - CONFIDENTIAL", fontsize=10, color=(0.3, 0.3, 0.3))
        p1.draw_line((50, 48), (545, 48), color=(0.7, 0.7, 0.7), width=1)
        p1.insert_text((50, 80), "PDF Visual Fidelity Document", fontsize=18, color=(0.1, 0.2, 0.6))
        p1.insert_text((50, 110), "Standard paragraph text evaluating font rendering and layout integrity.", fontsize=11)
        # Rectangles with colors
        p1.draw_rect(pymupdf.Rect(50, 140, 260, 200), color=(0.2, 0.6, 0.3), fill=(0.88, 0.96, 0.88), width=1.5)
        p1.insert_text((60, 175), "Green Accent Block", fontsize=12, color=(0.1, 0.4, 0.2))
        p1.draw_rect(pymupdf.Rect(280, 140, 545, 200), color=(0.8, 0.3, 0.2), fill=(0.98, 0.90, 0.88), width=1.5)
        p1.insert_text((290, 175), "Coral Accent Block", fontsize=12, color=(0.6, 0.1, 0.1))
        # Table
        p1.draw_rect(pymupdf.Rect(50, 220, 545, 245), fill=(0.15, 0.25, 0.45))
        p1.insert_text((60, 237), "Service", fontsize=10, color=(1, 1, 1))
        p1.insert_text((250, 237), "Tier", fontsize=10, color=(1, 1, 1))
        p1.insert_text((450, 237), "Price", fontsize=10, color=(1, 1, 1))
        p1.draw_rect(pymupdf.Rect(50, 245, 545, 270), fill=(0.95, 0.95, 0.98), color=(0.8, 0.8, 0.8), width=0.5)
        p1.insert_text((60, 262), "PDF Stealth Processing", fontsize=9)
        p1.insert_text((250, 262), "Basic", fontsize=9)
        p1.insert_text((450, 262), "$18.00", fontsize=9)
        # Footer
        p1.draw_line((50, 800), (545, 800), color=(0.7, 0.7, 0.7), width=1)
        p1.insert_text((50, 815), "Page 1 of 2", fontsize=9, color=(0.4, 0.4, 0.4))

        # Page 2: Landscape Letter (792 x 612 pt)
        p2 = doc.new_page(width=792, height=612)
        p2.insert_text((50, 50), "Landscape Technical Diagram / Table", fontsize=16, color=(0.1, 0.1, 0.3))
        p2.draw_rect(pymupdf.Rect(50, 70, 742, 550), color=(0.3, 0.5, 0.7), width=2)
        p2.insert_text((70, 110), "Verifying that landscape orientation (width > height) is preserved exactly.", fontsize=12)

        doc.save(self.input_pdf)
        doc.close()

        # Run conversion
        result = PDFToImagePDFConverter.convert(self.input_pdf, self.output_pdf, dpi=200)
        self.assertEqual(result["page_count"], 2)

        # Compare input vs output page by page
        doc_in = pymupdf.open(self.input_pdf)
        doc_out = pymupdf.open(self.output_pdf)

        self.assertEqual(len(doc_in), len(doc_out))

        for idx in range(len(doc_in)):
            p_in = doc_in[idx]
            p_out = doc_out[idx]

            # 1. Page dimensions must match exactly
            self.assertAlmostEqual(p_in.rect.width, p_out.rect.width, delta=0.5)
            self.assertAlmostEqual(p_in.rect.height, p_out.rect.height, delta=0.5)

            # 2. Render both at 200 DPI and verify high SSIM fidelity
            pix_in = p_in.get_pixmap(dpi=200)
            pix_out = p_out.get_pixmap(dpi=200)

            self.assertEqual(pix_in.width, pix_out.width)
            self.assertEqual(pix_in.height, pix_out.height)

            arr_in = np.frombuffer(pix_in.samples, dtype=np.uint8).reshape(pix_in.height, pix_in.width, pix_in.n)[:, :, :3]
            arr_out = np.frombuffer(pix_out.samples, dtype=np.uint8).reshape(pix_out.height, pix_out.width, pix_out.n)[:, :, :3]

            similarity = ssim(arr_in, arr_out)
            self.assertGreaterEqual(
                similarity, 0.990,
                f"Page {idx+1} SSIM {similarity:.5f} is below 0.990 fidelity threshold"
            )

        doc_in.close()
        doc_out.close()
