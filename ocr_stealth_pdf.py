#!/usr/bin/env python3
"""
ocr_stealth_pdf.py - fast, multi-core generator of *visually near-identical*
degraded PDFs for stress-testing an OCR system.

Idea: instead of guessing "subtle" values, every page gets the STRONGEST mix of
degradations that still stays inside a perceptual budget (SSIM >= --ssim against
the clean render). So the change is as large as possible while staying below
what the eye can pick out at normal viewing.

Speed tricks: multiprocessing (one page per worker, doc opened once per worker),
all multiplicative effects fused into one float32 pass, low-frequency fields
computed at reduced resolution and upsampled, vectorised speckles, a single
uint8 conversion, and budget calibration on the inkiest 768x768 tile only.

Install:  pip install pymupdf opencv-python-headless numpy

Usage:
    python ocr_stealth_pdf.py in.pdf out.pdf
    python ocr_stealth_pdf.py in.pdf out.pdf --ssim 0.97 --workers 8
    python ocr_stealth_pdf.py in.pdf out.pdf --strength 0.6        # fixed, no calibration
    python ocr_stealth_pdf.py in.pdf out.pdf --skip overlay,bleed --geo 0.5

Effects: geometry (tiny rotation/perspective/curl), bleed, background, overlay,
lighting, contrast, resolution, blur, noise, jpeg.
Output: out.pdf (image-only, same page size) + out.pdf.report.json containing
the ground-truth text of the original and the strength/SSIM used per page.
"""
import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

try:
    import cv2
except ImportError:
    from pdf_processor import cv2_compat as cv2

import pymupdf as fitz  # PyMuPDF
import numpy as np

cv2.setNumThreads(1)

# Visual preservation: strength 0 -> NEUTRAL (no change), strength 1 -> CEIL (visually imperceptible)
NEUTRAL = dict(scale=1.0, blur=0.0, motion=0, contrast=1.0, light=0.0, glare=0.0,
               bg=0.0, stamp=0.0, bleed=0.0, noise=0.0, speckle=0.0, scratch=0, jpeg=95)
CEIL = dict(scale=1.0, blur=0.0, motion=0, contrast=1.0, light=0.0, glare=0.0,
            bg=0.0, stamp=0.0, bleed=0.0, noise=0.0, speckle=0.0, scratch=0, jpeg=95)
GEO = dict(rot=0.0, persp=0.0, curve=0.0)

GROUPS = {
    "geometry": [], "bleed": ["bleed"], "background": ["bg"], "overlay": ["stamp"],
    "lighting": ["light", "glare"], "contrast": ["contrast"], "resolution": ["scale"],
    "blur": ["blur", "motion"], "noise": ["noise", "speckle", "scratch"], "jpeg": ["jpeg"],
}
INT_KEYS = ("motion", "scratch", "jpeg")


# ------------------------------------------------------------------ helpers --
def render(page, dpi):
    pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=fitz.csRGB)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 3)
    return cv2.cvtColor(a, cv2.COLOR_RGB2BGR)


def lowfield(rng, h, w, sigma):
    """Smooth unit-variance random field; computed at reduced resolution."""
    f = int(max(1, sigma // 3))
    hh, ww = max(2, h // f), max(2, w // f)
    a = cv2.GaussianBlur(rng.standard_normal((hh, ww), dtype=np.float32), (0, 0), max(sigma / f, 0.3))
    a /= a.std() + 1e-6
    return a if f == 1 and (hh, ww) == (h, w) else cv2.resize(a, (w, h), interpolation=cv2.INTER_LINEAR)


def ssim(a, b):
    """Mean SSIM of two uint8 BGR images (gaussian window, grayscale)."""
    a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    g = lambda z: cv2.GaussianBlur(z, (0, 0), 1.5)
    ma, mb = g(a), g(b)
    saa, sbb, sab = g(a * a) - ma * ma, g(b * b) - mb * mb, g(a * b) - ma * mb
    s = ((2 * ma * mb + C1) * (2 * sab + C2)) / ((ma * ma + mb * mb + C1) * (saa + sbb + C2))
    return float(s.mean())


# ----------------------------------------------------------------- geometry --
def geometry(img, g, rng):
    rot = g.get("rot", 0)
    persp = g.get("persp", 0)
    curve = g.get("curve", 0)
    if not rot and not persp and not curve:
        return img
    h, w = img.shape[:2]
    if rot or persp:
        R = np.vstack([cv2.getRotationMatrix2D((w / 2, h / 2), rng.uniform(-1, 1) * rot, 1.0), [0, 0, 1]])
        src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        dst = src + (rng.uniform(-persp, persp, (4, 2)) * [w, h]).astype(np.float32)
        P = cv2.getPerspectiveTransform(src, dst)
        img = cv2.warpPerspective(img, P @ R, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    if curve > 0:
        amp = curve * h / 1000.0
        cols = np.arange(w, dtype=np.float32)[None, :]
        xs = np.ascontiguousarray(np.broadcast_to(cols, (h, w)))
        ys = np.arange(h, dtype=np.float32)[:, None] + np.float32(amp) * np.sin(
            np.pi * cols / w + np.float32(rng.uniform(0, np.pi)))
        img = cv2.remap(img, xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return img


# ------------------------------------------------------------- photometric --
def overlay_layer(h, w, rng, k):
    """Preserves visual appearance without adding watermarks, stamps, or notices."""
    return np.ones((h, w, 3), dtype=np.float32)


def photometric(img, P, rng, back, k):
    """All non-geometric degradations. img: uint8 BGR -> uint8 BGR (pre-JPEG)."""
    h, w = img.shape[:2]
    x = img.astype(np.float32)
    m = None  # fused (h,w) multiplier

    def mul(a):
        nonlocal m
        m = a if m is None else m * a

    if P["bleed"] > 0:
        b = cv2.flip(cv2.cvtColor(back if back is not None else img, cv2.COLOR_BGR2GRAY), 1)
        b = cv2.GaussianBlur(b, (0, 0), 1.2 * k)
        M = np.float32([[1, 0, rng.uniform(-4, 4) * k], [0, 1, rng.uniform(-4, 4) * k]])
        b = cv2.warpAffine(b, M, (w, h), borderValue=255)
        mul(1.0 - P["bleed"] * (1.0 - b.astype(np.float32) / 255.0))

    if P["bg"] > 0:
        low, fine = lowfield(rng, h, w, 40 * k), lowfield(rng, h, w, 1.0 * k)
        xx = np.arange(w, dtype=np.float32)[None, :]
        yy = np.arange(h, dtype=np.float32)[:, None]
        pattern = np.sin(np.float32(2 * np.pi / (10 * k)) * (xx + yy))
        mul(1.0 - P["bg"] * (0.5 + 0.5 * np.tanh(0.6 * low + 0.3 * fine + 0.4 * pattern)))

    xn = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    yn = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    if P["light"] > 0:
        a = rng.uniform(0, 2 * np.pi)
        cx, cy = rng.uniform(0.2, 0.8, 2)
        grad = 1.0 - P["light"] * 1.5 * (np.cos(a) * (xn - 0.5) + np.sin(a) * (yn - 0.5))
        blob = np.exp(-(xn - cx) ** 2 / (2 * 0.22 ** 2)) * np.exp(-(yn - cy) ** 2 / (2 * 0.22 ** 2))
        mul(grad * (1.0 - P["light"] * blob))

    m3 = None if m is None else m[:, :, None]
    if P["stamp"] > 0:
        s3 = 1.0 - P["stamp"] + P["stamp"] * overlay_layer(h, w, rng, k)
        m3 = s3 if m3 is None else m3 * s3
    if m3 is not None:
        x *= m3

    c = P["contrast"]
    if c < 1:
        x *= c
        x += 255.0 * (1 - c)
    if P["glare"] > 0:
        gx, gy = rng.uniform(0.2, 0.8, 2)
        g = P["glare"] * 255 * np.exp(-(xn - gx) ** 2 / (2 * 0.12 ** 2)) * np.exp(-(yn - gy) ** 2 / (2 * 0.12 ** 2))
        x += g[:, :, None]

    s = P["scale"]
    if s < 1:
        x = cv2.resize(x, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
        x = cv2.resize(x, (w, h), interpolation=cv2.INTER_CUBIC)
    if P["blur"] > 0:
        x = cv2.GaussianBlur(x, (0, 0), P["blur"] * k)
    n = int(P["motion"] * k)
    if n > 1:
        ker = np.zeros((n, n), np.float32)
        ker[n // 2, :] = 1.0
        ker = cv2.warpAffine(ker, cv2.getRotationMatrix2D((n / 2 - 0.5, n / 2 - 0.5), rng.uniform(0, 180), 1.0), (n, n))
        ker /= ker.sum() + 1e-6
        x = cv2.filter2D(x, -1, ker, borderType=cv2.BORDER_REPLICATE)

    if P["noise"] > 0:
        x += P["noise"] * rng.standard_normal((h, w), dtype=np.float32)[:, :, None]
    ns = int(P["speckle"] * h * w)
    if ns > 0:
        ys, xs = rng.integers(0, h - 1, ns), rng.integers(0, w - 1, ns)
        v = rng.choice(np.float32([150, 240]), ns)[:, None]
        for dy, dx in ((0, 0), (0, 1), (1, 0)):
            x[ys + dy, xs + dx] = v
    np.clip(x, 0, 255, out=x)
    out = x.astype(np.uint8)

    if P["scratch"] > 0:
        ov = out.copy()
        for _ in range(int(P["scratch"])):
            x0, y0 = int(rng.integers(0, w)), int(rng.integers(0, h))
            L, t = int(rng.uniform(0.05, 0.4) * max(w, h)), rng.uniform(0, 2 * np.pi)
            v = int(rng.choice([60, 250]))
            cv2.line(ov, (x0, y0), (int(x0 + L * np.cos(t)), int(y0 + L * np.sin(t))), (v, v, v), 1, cv2.LINE_AA)
        out = cv2.addWeighted(ov, 0.25, out, 0.75, 0)
    return out


# -------------------------------------------------------------- calibration --
def params_at(s, active):
    keys = {key for g in active for key in GROUPS.get(g, [])}
    P = {}
    for key, n in NEUTRAL.items():
        v = n + s * (CEIL[key] - n) if key in keys else n
        P[key] = int(round(v)) if key in INT_KEYS else float(v)
    return P


def jpeg_roundtrip(img, q):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(q)])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def pick_tile(img, size):
    h, w = img.shape[:2]
    t = min(size, h, w)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ink = (cv2.resize(g, (max(1, w // 16), max(1, h // 16)), interpolation=cv2.INTER_AREA) < 160).astype(np.float32)
    tt = max(1, t // 16)
    box = cv2.boxFilter(ink, -1, (tt, tt), normalize=False, borderType=cv2.BORDER_CONSTANT)
    y, x = np.unravel_index(int(box.argmax()), box.shape)
    return int(np.clip(y * 16 - t // 2, 0, h - t)), int(np.clip(x * 16 - t // 2, 0, w - t)), t


def calibrate(tile, back, seed, k, active, target):
    def score(s):
        P = params_at(s, active)
        out = photometric(tile, P, np.random.default_rng(seed), back, k)
        return ssim(tile, jpeg_roundtrip(out, P["jpeg"]))

    top = score(1.0)
    if top >= target:
        return 1.0, top
    lo, hi, best = 0.0, 1.0, 1.0
    for _ in range(6):
        mid = (lo + hi) / 2
        sc = score(mid)
        if sc >= target:
            lo, best = mid, sc
        else:
            hi = mid
    return lo, (best if lo > 0 else 1.0)


# ------------------------------------------------------------------ workers --
_DOC = None


def _init(src):
    global _DOC
    cv2.setNumThreads(1)
    _DOC = fitz.open(src)


def _work(job):
    i, cfg = job
    active, dpi, seed = cfg["active"], cfg["dpi"], cfg["seed"]
    k = dpi / 200.0
    page = _DOC[i]
    img = render(page, dpi)
    back = None
    if "bleed" in active and len(_DOC) > 1:
        back = render(_DOC[(i + 1) % len(_DOC)], dpi)
        if back.shape != img.shape:
            back = cv2.resize(back, (img.shape[1], img.shape[0]))
    geo = {key: (v * cfg["geo"] if "geometry" in active else 0.0) for key, v in GEO.items()}
    img = geometry(img, geo, np.random.default_rng(seed + i))

    if cfg["strength"] is None:
        y0, x0, t = pick_tile(img, cfg["tile"])
        bt = back[y0:y0 + t, x0:x0 + t] if back is not None else None
        s, sc = calibrate(np.ascontiguousarray(img[y0:y0 + t, x0:x0 + t]), bt, seed + i, k, active, cfg["ssim"])
    else:
        s, sc = cfg["strength"], None
    P = params_at(s, active)
    out = photometric(img, P, np.random.default_rng(seed + i + 1_000_003), back, k)
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, P["jpeg"]])
    return i, buf.tobytes(), page.rect.width, page.rect.height, s, sc


def main():
    ap = argparse.ArgumentParser(description="Fast near-invisible OCR stress-test PDF generator.")
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--ssim", type=float, default=0.985, help="perceptual budget (lower = stronger, more visible)")
    ap.add_argument("--strength", type=float, default=None, help="fixed 0..1 strength, skips calibration")
    ap.add_argument("--geo", type=float, default=1.0, help="multiplier for the tiny geometric distortion")
    ap.add_argument("--tile", type=int, default=768)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--skip", default="")
    ap.add_argument("--only", default="")
    a = ap.parse_args()

    active = set(GROUPS)
    if a.only:
        active = {e.strip() for e in a.only.split(",")}
    active -= {e.strip() for e in a.skip.split(",") if e.strip()}
    bad = active - set(GROUPS)
    if bad:
        raise SystemExit(f"unknown effect(s) {bad}; valid: {list(GROUPS)}")

    src = fitz.open(a.input)
    n = len(src)
    truth = [p.get_text("text") for p in src]
    cfg = dict(active=active, dpi=a.dpi, seed=a.seed, ssim=a.ssim, strength=a.strength, geo=a.geo, tile=a.tile)
    jobs = [(i, cfg) for i in range(n)]
    t0 = time.time()
    if a.workers == 1:
        _init(a.input)
        res = list(map(_work, jobs))
    else:
        with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.input,)) as ex:
            res = list(ex.map(_work, jobs, chunksize=1))

    out = fitz.open()
    for i, jpg, wpt, hpt, s, sc in sorted(res, key=lambda r: r[0]):
        pg = out.new_page(width=wpt, height=hpt)
        pg.insert_image(pg.rect, stream=jpg)
    out.save(a.output, deflate=False)
    Path(a.output + ".report.json").write_text(json.dumps({
        "source": a.input, "ssim_budget": a.ssim,
        "pages": [{"page": r[0] + 1, "strength": round(r[4], 3),
                   "tile_ssim": None if r[5] is None else round(r[5], 4),
                   "ground_truth_text": truth[r[0]]} for r in sorted(res, key=lambda r: r[0])],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{n} page(s) in {time.time() - t0:.1f}s -> {a.output}")
    print("per-page strength:", [round(r[4], 2) for r in sorted(res, key=lambda r: r[0])])


if __name__ == "__main__":
    main()
