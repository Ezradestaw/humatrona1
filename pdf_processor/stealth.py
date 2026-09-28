"""
OCR Stealth PDF Degradation Engine.
Produces visually near-identical degraded images for stress-testing OCR systems
while staying strictly within a calibrated perceptual budget (SSIM >= budget).

Effects:
- geometry: subtle rotation, perspective, and wave curl
- bleed: subtle print bleed-through from adjacent pages
- background: paper texture and high/low-frequency fields
- overlay: faint stamps and watermark
- lighting: subtle illumination gradient and vignette
- contrast: slight contrast variation
- resolution: downscale and upscale
- blur: optical blur and motion smear
- noise: sensor noise, speckles, and fine scratches
- jpeg: controlled JPEG compression artifacts
"""
import logging
import numpy as np
from django.conf import settings

try:
    import cv2
except ImportError:
    from pdf_processor import cv2_compat as cv2

logger = logging.getLogger('humatron')

# strength 0 -> NEUTRAL (no change), strength 1 -> CEIL (strongest allowed)
NEUTRAL = dict(scale=1.0, blur=0.0, motion=0, contrast=1.0, light=0.0, glare=0.0,
               bg=0.0, stamp=0.0, bleed=0.0, noise=0.0, speckle=0.0, scratch=0, jpeg=95)
CEIL = dict(scale=0.50, blur=1.2, motion=3, contrast=0.70, light=0.15, glare=0.10,
            bg=0.10, stamp=0.12, bleed=0.12, noise=8.0, speckle=0.0006, scratch=5, jpeg=35)
# geometry is not searched (SSIM punishes sub-pixel shifts that are imperceptible);
# it is applied at fixed tiny values and the photometric budget is measured after it
GEO = dict(rot=0.15, persp=0.002, curve=0.5)

GROUPS = {
    "geometry": [],
    "bleed": ["bleed"],
    "background": ["bg"],
    "overlay": ["stamp"],
    "lighting": ["light", "glare"],
    "contrast": ["contrast"],
    "resolution": ["scale"],
    "blur": ["blur", "motion"],
    "noise": ["noise", "speckle", "scratch"],
    "jpeg": ["jpeg"],
}
INT_KEYS = ("motion", "scratch", "jpeg")


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


def geometry(img, g, rng):
    """Applies subtle rotation, perspective, and wave curl to image."""
    h, w = img.shape[:2]
    if g.get("rot", 0) or g.get("persp", 0):
        R = np.vstack([cv2.getRotationMatrix2D((w / 2, h / 2), rng.uniform(-1, 1) * g.get("rot", 0), 1.0), [0, 0, 1]])
        src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        dst = src + (rng.uniform(-g.get("persp", 0), g.get("persp", 0), (4, 2)) * [w, h]).astype(np.float32)
        P = cv2.getPerspectiveTransform(src, dst)
        img = cv2.warpPerspective(img, P @ R, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    if g.get("curve", 0) > 0:
        amp = g["curve"] * h / 1000.0
        cols = np.arange(w, dtype=np.float32)[None, :]
        xs = np.ascontiguousarray(np.broadcast_to(cols, (h, w)))
        ys = np.arange(h, dtype=np.float32)[:, None] + np.float32(amp) * np.sin(
            np.pi * cols / w + np.float32(rng.uniform(0, np.pi)))
        img = cv2.remap(img, xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return img


def overlay_layer(h, w, rng, k):
    """Faint stamps + diagonal watermark, drawn at 1/4 resolution then upsampled."""
    f = 4
    hh, ww = max(2, h // f), max(2, w // f)
    font = cv2.FONT_HERSHEY_DUPLEX
    layer = np.full((hh, ww, 3), 255, np.uint8)
    th = max(1, int(3 * k / f))
    for _ in range(2):
        cx, cy = int(rng.uniform(0.15, 0.85) * ww), int(rng.uniform(0.15, 0.85) * hh)
        r = max(5, int(0.07 * ww))
        col = (int(rng.uniform(40, 90)), int(rng.uniform(40, 90)), int(rng.uniform(150, 220)))
        cv2.circle(layer, (cx, cy), r, col, th, cv2.LINE_AA)
        cv2.circle(layer, (cx, cy), max(2, int(r * 0.8)), col, th, cv2.LINE_AA)
        cv2.putText(layer, "APPROVED", (cx - int(r * 0.75), cy + int(r * 0.1)), font, max(0.2, r / 55.0), col, th, cv2.LINE_AA)
    wm = np.full((hh, ww, 3), 255, np.uint8)
    cv2.putText(wm, "CONFIDENTIAL", (int(0.12 * ww), int(0.55 * hh)), font, max(0.3, ww / 350.0), (150, 150, 150),
                max(1, int(4 * k / f)), cv2.LINE_AA)
    wm = cv2.warpAffine(wm, cv2.getRotationMatrix2D((ww / 2, hh / 2), 35, 1.0), (ww, hh), borderValue=(255, 255, 255))
    layer = np.minimum(layer, wm)
    return cv2.resize(layer, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0


def photometric(img, P, rng, back, k):
    """All non-geometric degradations. img: uint8 BGR -> uint8 BGR (pre-JPEG)."""
    h, w = img.shape[:2]
    x = img.astype(np.float32)
    m = None

    def mul(a):
        nonlocal m
        m = a if m is None else m * a

    if P.get("bleed", 0) > 0:
        b = cv2.flip(cv2.cvtColor(back if back is not None else img, cv2.COLOR_BGR2GRAY), 1)
        b = cv2.GaussianBlur(b, (0, 0), 1.2 * k)
        M = np.float32([[1, 0, rng.uniform(-4, 4) * k], [0, 1, rng.uniform(-4, 4) * k]])
        b = cv2.warpAffine(b, M, (w, h), borderValue=255)
        mul(1.0 - P["bleed"] * (1.0 - b.astype(np.float32) / 255.0))

    if P.get("bg", 0) > 0:
        low, fine = lowfield(rng, h, w, 40 * k), lowfield(rng, h, w, 1.0 * k)
        xx = np.arange(w, dtype=np.float32)[None, :]
        yy = np.arange(h, dtype=np.float32)[:, None]
        pattern = np.sin(np.float32(2 * np.pi / (10 * k)) * (xx + yy))
        mul(1.0 - P["bg"] * (0.5 + 0.5 * np.tanh(0.6 * low + 0.3 * fine + 0.4 * pattern)))

    xn = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    yn = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    if P.get("light", 0) > 0:
        a = rng.uniform(0, 2 * np.pi)
        cx, cy = rng.uniform(0.2, 0.8, 2)
        grad = 1.0 - P["light"] * 1.5 * (np.cos(a) * (xn - 0.5) + np.sin(a) * (yn - 0.5))
        blob = np.exp(-(xn - cx) ** 2 / (2 * 0.22 ** 2)) * np.exp(-(yn - cy) ** 2 / (2 * 0.22 ** 2))
        mul(grad * (1.0 - P["light"] * blob))

    m3 = None if m is None else m[:, :, None]
    if P.get("stamp", 0) > 0:
        s3 = 1.0 - P["stamp"] + P["stamp"] * overlay_layer(h, w, rng, k)
        m3 = s3 if m3 is None else m3 * s3
    if m3 is not None:
        x *= m3

    c = P.get("contrast", 1.0)
    if c < 1:
        x *= c
        x += 255.0 * (1 - c)
    if P.get("glare", 0) > 0:
        gx, gy = rng.uniform(0.2, 0.8, 2)
        g = P["glare"] * 255 * np.exp(-(xn - gx) ** 2 / (2 * 0.12 ** 2)) * np.exp(-(yn - gy) ** 2 / (2 * 0.12 ** 2))
        x += g[:, :, None]

    s = P.get("scale", 1.0)
    if s < 1:
        x = cv2.resize(x, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
        x = cv2.resize(x, (w, h), interpolation=cv2.INTER_CUBIC)
    if P.get("blur", 0) > 0:
        x = cv2.GaussianBlur(x, (0, 0), P["blur"] * k)
    n = int(P.get("motion", 0) * k)
    if n > 1:
        ker = np.zeros((n, n), np.float32)
        ker[n // 2, :] = 1.0
        ker = cv2.warpAffine(ker, cv2.getRotationMatrix2D((n / 2 - 0.5, n / 2 - 0.5), rng.uniform(0, 180), 1.0), (n, n))
        ker /= ker.sum() + 1e-6
        x = cv2.filter2D(x, -1, ker, borderType=cv2.BORDER_REPLICATE)

    if P.get("noise", 0) > 0:
        x += P["noise"] * rng.standard_normal((h, w), dtype=np.float32)[:, :, None]
    ns = int(P.get("speckle", 0) * h * w)
    if ns > 0:
        ys, xs = rng.integers(0, max(1, h - 1), ns), rng.integers(0, max(1, w - 1), ns)
        v = rng.choice(np.float32([150, 240]), ns)[:, None]
        for dy, dx in ((0, 0), (0, 1), (1, 0)):
            x[np.clip(ys + dy, 0, h - 1), np.clip(xs + dx, 0, w - 1)] = v
    np.clip(x, 0, 255, out=x)
    out = x.astype(np.uint8)

    if P.get("scratch", 0) > 0:
        ov = out.copy()
        for _ in range(int(P["scratch"])):
            x0, y0 = int(rng.integers(0, w)), int(rng.integers(0, h))
            L, t = int(rng.uniform(0.05, 0.4) * max(w, h)), rng.uniform(0, 2 * np.pi)
            v = int(rng.choice([60, 250]))
            cv2.line(ov, (x0, y0), (int(x0 + L * np.cos(t)), int(y0 + L * np.sin(t))), (v, v, v), 1, cv2.LINE_AA)
        out = cv2.addWeighted(ov, 0.25, out, 0.75, 0)
    return out


def params_at(s, active):
    """Interpolate parameter set between NEUTRAL and CEIL at given strength s in [0, 1]."""
    keys = {key for g in active for key in GROUPS.get(g, [])}
    P = {}
    for key, n in NEUTRAL.items():
        v = n + s * (CEIL[key] - n) if key in keys else n
        P[key] = int(round(v)) if key in INT_KEYS else float(v)
    return P


def jpeg_roundtrip(img, q):
    """Encodes and decodes an image via JPEG compression at quality q."""
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(q)])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def pick_tile(img, size):
    """Finds the inkiest tile of size x size in the document for SSIM calibration."""
    h, w = img.shape[:2]
    t = min(size, h, w)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ink = (cv2.resize(g, (max(1, w // 16), max(1, h // 16)), interpolation=cv2.INTER_AREA) < 160).astype(np.float32)
    tt = max(1, t // 16)
    box = cv2.boxFilter(ink, -1, (tt, tt), normalize=False, borderType=cv2.BORDER_CONSTANT)
    y, x = np.unravel_index(int(box.argmax()), box.shape)
    return int(np.clip(y * 16 - t // 2, 0, max(0, h - t))), int(np.clip(x * 16 - t // 2, 0, max(0, w - t))), t


def calibrate(tile, back, seed, k, active, target):
    """Binary search for maximum degradation strength s in [0, 1] while SSIM >= target."""
    def score(s):
        P = params_at(s, active)
        out = photometric(tile, P, np.random.default_rng(seed), back, k)
        return ssim(tile, jpeg_roundtrip(out, P["jpeg"]))

    top = score(1.0)
    if top >= target:
        return 1.0, top
    lo, hi, best = 0.0, 1.0, 1.0
    for _ in range(4):
        mid = (lo + hi) / 2
        sc = score(mid)
        if sc >= target:
            lo, best = mid, sc
        else:
            hi = mid
    return lo, (best if lo > 0 else 1.0)


def apply_stealth_degradation(img_bgr, back_bgr=None, dpi=150, page_idx=0, config=None):
    """
    Applies calibrated stealth degradations to a page raster (in uint8 BGR).
    Parameters are driven by environment variables / settings or the config dict.

    Returns:
        tuple (jpg_bytes: bytes, report: dict)
    """
    cfg = config or {}

    enabled = cfg.get('enabled', getattr(settings, 'PDF_STEALTH_ENABLED', True))
    if not enabled:
        ok, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
        return buf.tobytes(), {'enabled': False, 'strength': 0.0, 'ssim': 1.0}

    target_ssim = cfg.get('ssim', getattr(settings, 'PDF_STEALTH_SSIM', 0.985))
    fixed_strength = cfg.get('strength', getattr(settings, 'PDF_STEALTH_STRENGTH', None))
    geo_mult = cfg.get('geo', getattr(settings, 'PDF_STEALTH_GEO', 1.0))
    tile_size = cfg.get('tile', getattr(settings, 'PDF_STEALTH_TILE', 256))
    seed = cfg.get('seed', getattr(settings, 'PDF_STEALTH_SEED', 0)) + page_idx
    skip = cfg.get('skip', getattr(settings, 'PDF_STEALTH_SKIP', ''))
    only = cfg.get('only', getattr(settings, 'PDF_STEALTH_ONLY', ''))

    active = set(GROUPS)
    if only:
        active = {e.strip() for e in only.split(",") if e.strip()}
    if skip:
        active -= {e.strip() for e in skip.split(",") if e.strip()}

    k = float(dpi) / 200.0

    # Ensure back page matches shape if bleed is active
    back = None
    if "bleed" in active and back_bgr is not None:
        back = back_bgr
        if back.shape != img_bgr.shape:
            back = cv2.resize(back, (img_bgr.shape[1], img_bgr.shape[0]))

    # Step 1: Geometry distortion
    geo = {key: (v * geo_mult if "geometry" in active else 0.0) for key, v in GEO.items()}
    rng_geo = np.random.default_rng(seed)
    processed = geometry(img_bgr.copy(), geo, rng_geo)

    # Step 2: SSIM Calibration or fixed strength
    if fixed_strength is None:
        y0, x0, t = pick_tile(processed, tile_size)
        bt = back[y0:y0 + t, x0:x0 + t] if back is not None else None
        tile = np.ascontiguousarray(processed[y0:y0 + t, x0:x0 + t])
        s, sc = calibrate(tile, bt, seed, k, active, target_ssim)
    else:
        s = float(fixed_strength)
        sc = None

    # Step 3: Photometric degradation
    P = params_at(s, active)
    rng_photo = np.random.default_rng(seed + 1_000_003)
    out = photometric(processed, P, rng_photo, back, k)

    # Step 4: Encode to JPEG
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, P["jpeg"]])

    report = {
        'enabled': True,
        'page': page_idx + 1,
        'strength': round(s, 4),
        'tile_ssim': None if sc is None else round(sc, 4),
        'target_ssim': target_ssim,
        'jpeg_quality': P["jpeg"],
    }
    return buf.tobytes(), report
