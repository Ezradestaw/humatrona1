import os
import json
import tempfile
import subprocess
from django.test import TestCase, override_settings
from django.conf import settings
import pymupdf

from pdf_processor.converter import PDFToImagePDFConverter, PDFConversionError
from pdf_processor.stealth import apply_stealth_degradation, calibrate, geometry, ssim


class PDFStealthDegradationTests(TestCase):
    """
    Test suite for the OCR Stealth PDF degradation engine and its integration
    into the Humatron conversion pipeline.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.input_pdf = os.path.join(self.temp_dir, "test_input.pdf")
        self.output_pdf = os.path.join(self.temp_dir, "test_output.pdf")

        # Create a sample multi-page PDF with text and vector graphics
        doc = pymupdf.open()
        p1 = doc.new_page(width=595, height=842)
        p1.insert_text((50, 72), "Humatron Stealth Document - Confidential", fontsize=16)
        p1.insert_text((50, 120), "This text should be flattened into a visually degraded raster layer.", fontsize=11)
        p1.draw_rect(pymupdf.Rect(50, 150, 545, 300), color=(0.2, 0.4, 0.8), fill=(0.9, 0.95, 1.0))
        p1.insert_text((70, 200), "Protected content inside rectangle", fontsize=12)

        p2 = doc.new_page(width=595, height=842)
        p2.insert_text((50, 72), "Page 2 - Secondary Section", fontsize=14)
        p2.insert_text((50, 110), "Bleed-through source page for multi-page test.", fontsize=11)

        doc.save(self.input_pdf)
        doc.close()

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_stealth_conversion_enabled_default(self):
        """Verify standard conversion applies stealth degradation and satisfies minimal metadata."""
        result = PDFToImagePDFConverter.convert(self.input_pdf, self.output_pdf, dpi=120)

        self.assertEqual(result['page_count'], 2)
        self.assertTrue(os.path.exists(self.output_pdf))
        self.assertGreater(result['output_size_bytes'], 0)

        # Inspect output document
        out_doc = pymupdf.open(self.output_pdf)
        self.assertEqual(len(out_doc), 2)

        # 1. No selectable text (flattened to image)
        for page in out_doc:
            self.assertEqual(page.get_text().strip(), "")

        # 2. Minimal controlled metadata (no original metadata leakage)
        meta = out_doc.metadata
        self.assertEqual(meta.get('producer'), "Humatron PDF Processor")
        self.assertFalse(meta.get('author'))
        self.assertFalse(meta.get('creationDate'))

        # 3. Stealth reports present
        self.assertIn('stealth_reports', result)
        self.assertEqual(len(result['stealth_reports']), 2)
        r0 = result['stealth_reports'][0]
        self.assertTrue(r0['enabled'])
        self.assertIn('strength', r0)
        self.assertGreaterEqual(r0['strength'], 0.0)
        out_doc.close()

    def test_stealth_conversion_disabled_setting(self):
        """Verify stealth degradation can be disabled via setting."""
        with override_settings(PDF_STEALTH_ENABLED=False):
            result = PDFToImagePDFConverter.convert(self.input_pdf, self.output_pdf, dpi=100)

            self.assertEqual(result['page_count'], 2)
            self.assertTrue(os.path.exists(self.output_pdf))

            for rep in result['stealth_reports']:
                self.assertFalse(rep['enabled'])

            out_doc = pymupdf.open(self.output_pdf)
            self.assertEqual(len(out_doc), 2)
            self.assertEqual(out_doc.metadata.get('producer'), "Humatron PDF Processor")
            out_doc.close()

    def test_stealth_fixed_strength_override(self):
        """Verify fixed strength bypasses binary search calibration."""
        with override_settings(PDF_STEALTH_STRENGTH=0.45):
            result = PDFToImagePDFConverter.convert(self.input_pdf, self.output_pdf, dpi=100)
            self.assertEqual(len(result['stealth_reports']), 2)
            self.assertEqual(result['stealth_reports'][0]['strength'], 0.45)
            self.assertIsNone(result['stealth_reports'][0]['tile_ssim'])

    def test_stealth_custom_ssim_budget(self):
        """Verify higher SSIM budget constrains degradation strength."""
        cfg_high = {'enabled': True, 'ssim': 0.995, 'strength': None, 'tile': 256}
        res_high = PDFToImagePDFConverter.convert(
            self.input_pdf, self.output_pdf, dpi=100, stealth_config=cfg_high
        )
        s_high = res_high['stealth_reports'][0]['strength']

        cfg_low = {'enabled': True, 'ssim': 0.900, 'strength': None, 'tile': 256}
        res_low = PDFToImagePDFConverter.convert(
            self.input_pdf, self.output_pdf, dpi=100, stealth_config=cfg_low
        )
        s_low = res_low['stealth_reports'][0]['strength']

        # A looser budget (0.90) allows equal or stronger degradation than strict (0.995)
        self.assertGreaterEqual(s_low, s_high)

    def test_standalone_cli_script(self):
        """Verify ocr_stealth_pdf.py runs directly from the command line."""
        cli_script = os.path.join(settings.BASE_DIR, "ocr_stealth_pdf.py")
        self.assertTrue(os.path.exists(cli_script))

        cli_out = os.path.join(self.temp_dir, "cli_output.pdf")
        cmd = [
            "./venv/bin/python",
            cli_script,
            self.input_pdf,
            cli_out,
            "--dpi", "100",
            "--ssim", "0.98",
            "--workers", "1",
            "--tile", "256",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=settings.BASE_DIR)
        self.assertEqual(proc.returncode, 0, f"CLI script failed: {proc.stderr}")

        # Check output PDF was created and is valid
        self.assertTrue(os.path.exists(cli_out))
        doc = pymupdf.open(cli_out)
        self.assertEqual(len(doc), 2)
        doc.close()

        # Check report JSON
        report_file = cli_out + ".report.json"
        self.assertTrue(os.path.exists(report_file))
        with open(report_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn("pages", data)
        self.assertEqual(len(data["pages"]), 2)
        self.assertIn("strength", data["pages"][0])
        self.assertIn("ground_truth_text", data["pages"][0])
