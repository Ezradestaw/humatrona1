#!/usr/bin/env python3
"""
subtle_noise_ocr.py - Subtle Gaussian image noise pre-processing & invisible Unicode OCR PDF generator.

Pipeline:
1. add_subtle_noise / apply_subtle_noise:
   Adds very subtle Gaussian noise to image pixels before PDF conversion.
   Strength scale:
       0.1 = extremely subtle
       0.5 = very subtle
       1.0 = subtle
       2.0 = noticeable

2. ocr_page:
   Renders scanned PDF page and extracts text and bounding boxes using pytesseract.

3. insert_invisible_chars:
   Inserts zero-width spaces (ZWSP = "\\u200b") sparsely into text while staying
   strictly within the MAX_INVISIBLE_BYTES budget.

4. create_pdf / process_pdf_with_noise_and_invisible_ocr:
   Constructs a clean PDF preserving exact page dimensions and image visuals,
   embedding an invisible text layer (render_mode=3) with sparse ZWSP characters.
   Ensures everything remains visually normal and indistinguishable from original.
"""

import io
import os
import shutil
import logging
import numpy as np
from PIL import Image
import pymupdf as fitz
import pytesseract

logger = logging.getLogger('humatron')

# Invisible Unicode character (Zero-Width Space)
ZWSP = "\u200b"

# Maximum UTF-8 bytes allocated to inserted characters (1 MB)
MAX_INVISIBLE_BYTES = 1024 * 1024

# Ensure pytesseract can find tesseract across environments
_KNOWN_TESSERACT_PATHS = [
    "/home/anonymous/.local/bin/tesseract",
    "/home/anonymous/Downloads/stealth/venv/bin/tesseract",
    "/home/anonymous/Downloads/stealth/opt/tesseract/usr/bin/tesseract",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
]

def _configure_tesseract_environment():
    opt_tess = "/home/anonymous/Downloads/stealth/opt/tesseract"
    if os.path.exists(opt_tess):
        tessdata = os.path.join(opt_tess, "usr/share/tesseract-ocr/5/tessdata")
        if os.path.exists(tessdata) and "TESSDATA_PREFIX" not in os.environ:
            os.environ["TESSDATA_PREFIX"] = tessdata
        tess_lib = os.path.join(opt_tess, "usr/lib/x86_64-linux-gnu")
        if os.path.exists(tess_lib):
            curr_ld = os.environ.get("LD_LIBRARY_PATH", "")
            if tess_lib not in curr_ld:
                os.environ["LD_LIBRARY_PATH"] = f"{tess_lib}:{curr_ld}" if curr_ld else tess_lib

    if not shutil.which("tesseract"):
        for p in _KNOWN_TESSERACT_PATHS:
            if os.path.exists(p):
                pytesseract.pytesseract.tesseract_cmd = p
                break

_configure_tesseract_environment()


# ----------------------------------------------------------------------
# 1. Subtle Gaussian Noise Processing
# ----------------------------------------------------------------------

def apply_subtle_noise(image: Image.Image, strength: float = 0.2) -> Image.Image:
    """
    In-memory helper to add extremely subtle Gaussian noise to a PIL Image.

    strength:
        0.1 = extremely subtle
        0.5 = very subtle
        1.0 = subtle
        2.0 = noticeable
    """
    rgb_image = image.convert("RGB") if image.mode != "RGB" else image
    pixels = np.asarray(rgb_image).astype(np.float32)

    # Generate small random variations
    noise = np.random.normal(
        loc=0,
        scale=strength,
        size=pixels.shape
    )

    # Apply noise and clamp to valid uint8 RGB range
    noisy = np.clip(pixels + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(noisy)


def add_subtle_noise(input_path: str, output_path: str, strength: float = 0.2):
    """
    Add very subtle Gaussian noise to an image file.

    strength:
        0.1  = extremely subtle
        0.5  = very subtle
        1.0  = subtle
        2.0  = noticeable
    """
    image = Image.open(input_path).convert("RGB")
    pixels = np.asarray(image).astype(np.float32)

    # Generate small random variations
    noise = np.random.normal(
        loc=0,
        scale=strength,
        size=pixels.shape
    )

    # Apply noise
    noisy = pixels + noise

    # Keep valid RGB range
    noisy = np.clip(noisy, 0, 255).astype(np.uint8)

    Image.fromarray(noisy).save(output_path, quality=100)


# ----------------------------------------------------------------------
# 2. Sparse Zero-Width Character Insertion
# ----------------------------------------------------------------------

def insert_invisible_chars(text: str, max_bytes: int, step: int = 10, word_index: int = None) -> str:
    """
    Insert zero-width characters while keeping their UTF-8
    representation below max_bytes.

    Supports both multi-word text strings and word-by-word streaming.
    - If text contains multiple words, inserts approximately one ZWSP every `step` words.
    - If text is a single word and `word_index` is provided, inserts ZWSP when (word_index % step == 0).
    """
    if not text:
        return text

    # U+200B occupies 3 UTF-8 bytes.
    char_bytes = len(ZWSP.encode("utf-8"))

    # Don't exceed the requested limit.
    maximum = max_bytes // char_bytes
    if maximum <= 0:
        return text

    words = text.split(" ")

    if len(words) > 1:
        result = []
        inserted = 0

        # Approximately one insertion every 10 words.
        for i, word in enumerate(words):
            result.append(word)

            if (
                i % step == 0
                and i != 0
                and inserted < maximum
            ):
                result.append(ZWSP)
                inserted += 1

            if inserted >= maximum:
                break

        # Preserve remaining text if the limit was reached.
        if i + 1 < len(words):
            result.extend(words[i + 1:])

        return " ".join(result)
    else:
        # Single word evaluation
        if word_index is not None and word_index % step == 0 and word_index != 0 and maximum >= 1:
            return text + ZWSP
        return text


# ----------------------------------------------------------------------
# 3. Page OCR
# ----------------------------------------------------------------------

def ocr_page(page, dpi: int = 200) -> dict:
    """
    Render a scanned PDF page and OCR it using pytesseract.
    Returns pytesseract data dictionary containing level, left, top, width, height, text.
    """
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=matrix, alpha=False)

    image = Image.open(
        io.BytesIO(pix.tobytes("png"))
    )

    try:
        return pytesseract.image_to_data(
            image,
            output_type=pytesseract.Output.DICT
        )
    except Exception as exc:
        logger.warning("pytesseract OCR warning on page: %s", exc)
        return {"text": [], "left": [], "top": [], "width": [], "height": []}


# ----------------------------------------------------------------------
# 4. Invisible Text Layer Application
# ----------------------------------------------------------------------

def apply_invisible_ocr_layer(
    new_page,
    page_rect,
    ocr_data: dict,
    total_invisible_bytes: int = 0,
    max_invisible_bytes: int = MAX_INVISIBLE_BYTES,
) -> int:
    """
    Embeds an invisible text layer (render_mode=3) into new_page based on OCR output.
    Positions each word at its detected bounding box scaled back to PDF points.
    Returns the total bytes added during this page insertion.
    """
    if not ocr_data or not ocr_data.get("text"):
        return 0

    # Retrieve full OCR image dimensions from Level 1 (page-level entry at index 0)
    ocr_w = ocr_data["width"][0] if (ocr_data.get("width") and ocr_data["width"][0] > 0) else (ocr_data["width"][-1] if ocr_data.get("width") else 1)
    ocr_h = ocr_data["height"][0] if (ocr_data.get("height") and ocr_data["height"][0] > 0) else (ocr_data["height"][-1] if ocr_data.get("height") else 1)

    scale_x = page_rect.width / ocr_w if ocr_w else 1
    scale_y = page_rect.height / ocr_h if ocr_h else 1

    # Attempt to embed a TrueType Unicode font for literal ZWSP UTF-8 support
    fontname = None
    for font_cand in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]:
        if os.path.exists(font_cand):
            try:
                new_page.insert_font(fontname="f_zwsp", fontfile=font_cand)
                fontname = "f_zwsp"
                break
            except Exception:
                fontname = None

    font_kwargs = {"fontname": fontname} if fontname else {}

    bytes_added_page = 0
    char_bytes = len(ZWSP.encode("utf-8"))

    word_idx = 0
    for i, word in enumerate(ocr_data["text"]):
        word = word.strip()
        if not word:
            continue

        word_idx += 1

        # Coordinates from OCR image
        x = ocr_data["left"][i]
        y = ocr_data["top"][i]
        w = ocr_data["width"][i]
        h = ocr_data["height"][i]

        budget_remaining = max_invisible_bytes - (total_invisible_bytes + bytes_added_page)
        modified = insert_invisible_chars(
            word,
            budget_remaining,
            step=10,
            word_index=word_idx
        )

        added = (
            len(modified.encode("utf-8"))
            - len(word.encode("utf-8"))
        )

        if budget_remaining - added < 0:
            modified = word
        else:
            bytes_added_page += added

        # Convert OCR coordinates back to PDF coordinates
        rect = fitz.Rect(
            x * scale_x,
            y * scale_y,
            (x + w) * scale_x,
            (y + h) * scale_y
        )

        fontsize = max(1.0, h * scale_y * 0.8)

        # Insert invisible PDF text (render_mode=3: neither fill nor stroke text)
        res = new_page.insert_textbox(
            rect,
            modified,
            fontsize=fontsize,
            render_mode=3,
            **font_kwargs
        )
        if res < 0:
            # Fallback for tight bounding boxes to ensure word placement without overflow
            try:
                new_page.insert_text(
                    fitz.Point(x * scale_x, (y + h) * scale_y),
                    modified,
                    fontsize=fontsize,
                    render_mode=3,
                    **font_kwargs
                )
            except Exception:
                pass

    return bytes_added_page


# ----------------------------------------------------------------------
# 5. Full PDF Processing Routine
# ----------------------------------------------------------------------

def create_pdf(
    input_path: str = "input.pdf",
    output_path: str = "output.pdf",
    noise_strength: float = 0.2,
    ocr_dpi: int = 200,
    max_invisible_bytes: int = MAX_INVISIBLE_BYTES,
):
    """
    Creates a new flattened, noise-treated image-based PDF with an embedded
    invisible Unicode OCR text layer.
    
    Guarantees:
    - Exactly preserves page dimensions and visual appearance.
    - Page images receive subtle Gaussian noise (imperceptible to human eye).
    - An invisible OCR text layer (render_mode=3) is added at original positions.
    - Zero-width spaces (ZWSP) are inserted sparsely up to max_invisible_bytes.
    - Resulting PDF looks completely normal to visual inspection.
    """
    source = fitz.open(input_path)
    output = fitz.open()

    total_invisible_bytes = 0

    try:
        for page_number, page in enumerate(source):
            logger.info("Processing page %d/%d", page_number + 1, len(source))

            # 1. Render page image
            pix = page.get_pixmap(alpha=False)
            page_img = Image.open(io.BytesIO(pix.tobytes("png")))

            # 2. Apply subtle Gaussian noise before converting to PDF
            if noise_strength and noise_strength > 0:
                noisy_img = apply_subtle_noise(page_img, strength=noise_strength)
            else:
                noisy_img = page_img

            # Convert to PNG / JPEG bytes
            img_buf = io.BytesIO()
            noisy_img.save(img_buf, format="JPEG", quality=98)
            img_bytes = img_buf.getvalue()

            # 3. Create destination page with exact width/height
            new_page = output.new_page(
                width=page.rect.width,
                height=page.rect.height
            )

            # 4. Insert image to completely occupy original page boundaries
            new_page.insert_image(
                page.rect,
                stream=img_bytes
            )

            # 5. OCR page at configured DPI
            data = ocr_page(page, dpi=ocr_dpi)

            # 6. Insert invisible Unicode OCR text layer (render_mode=3)
            added = apply_invisible_ocr_layer(
                new_page=new_page,
                page_rect=page.rect,
                ocr_data=data,
                total_invisible_bytes=total_invisible_bytes,
                max_invisible_bytes=max_invisible_bytes,
            )
            total_invisible_bytes += added

        output.save(
            output_path,
            garbage=4,
            deflate=True
        )

        logger.info("Inserted invisible Unicode data: %d bytes into %s",
                    total_invisible_bytes, output_path)

    finally:
        output.close()
        source.close()

    return total_invisible_bytes


if __name__ == "__main__":
    import sys
    in_file = sys.argv[1] if len(sys.argv) > 1 else "input.pdf"
    out_file = sys.argv[2] if len(sys.argv) > 2 else "output.pdf"

    if in_file.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        print(f"Applying subtle Gaussian noise to image: {in_file} -> {out_file}")
        add_subtle_noise(in_file, out_file, strength=0.2)
    elif os.path.exists(in_file):
        print(f"Processing PDF with subtle noise & invisible OCR: {in_file} -> {out_file}")
        create_pdf(in_file, out_file, noise_strength=0.2)
    else:
        print(f"File not found: {in_file}. Specify input.pdf output.pdf or input.jpg output.jpg")
