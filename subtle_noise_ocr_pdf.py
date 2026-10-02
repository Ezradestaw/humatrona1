#!/usr/bin/env python3
"""
subtle_noise_ocr_pdf.py - Standalone utility for subtle image noise & invisible Unicode OCR PDF conversion.
Usage:
    python subtle_noise_ocr_pdf.py input.pdf output.pdf
    python subtle_noise_ocr_pdf.py input.jpg output.jpg
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdf_processor.subtle_noise_ocr import (
    add_subtle_noise,
    apply_subtle_noise,
    insert_invisible_chars,
    ocr_page,
    create_pdf,
    ZWSP,
    MAX_INVISIBLE_BYTES,
)

if __name__ == "__main__":
    in_file = sys.argv[1] if len(sys.argv) > 1 else "input.pdf"
    out_file = sys.argv[2] if len(sys.argv) > 2 else "output.pdf"

    if in_file.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        print(f"Applying subtle Gaussian noise to image: {in_file} -> {out_file}")
        add_subtle_noise(in_file, out_file, strength=0.2)
    elif os.path.exists(in_file):
        print(f"Processing PDF with subtle noise & invisible OCR: {in_file} -> {out_file}")
        bytes_added = create_pdf(in_file, out_file, noise_strength=0.2)
        print(f"Done! Inserted {bytes_added} invisible Unicode bytes into {out_file}")
    else:
        print(f"Usage: python subtle_noise_ocr_pdf.py <input.pdf|input.jpg> <output.pdf|output.jpg>")
