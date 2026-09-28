"""
OpenCV (cv2) compatibility and fallback module.
Provides cv2 functions using NumPy, SciPy (scipy.ndimage), and PIL when native
opencv-python is not installed, and seamlessly wraps native cv2 when available.
"""
import io
import sys
import numpy as np
import scipy.ndimage
from PIL import Image, ImageDraw

# Constants
INTER_NEAREST = 0
INTER_LINEAR = 1
INTER_CUBIC = 2
INTER_AREA = 3

BORDER_CONSTANT = 0
BORDER_REPLICATE = 1
BORDER_REFLECT = 2

COLOR_RGB2BGR = 4
COLOR_BGR2RGB = 4
COLOR_BGR2GRAY = 6
COLOR_RGB2GRAY = 7
COLOR_GRAY2BGR = 8
COLOR_GRAY2RGB = 8

FONT_HERSHEY_SIMPLEX = 0
FONT_HERSHEY_PLAIN = 1
FONT_HERSHEY_DUPLEX = 2
LINE_AA = 16

IMWRITE_JPEG_QUALITY = 1
IMREAD_COLOR = 1
IMREAD_GRAYSCALE = 0

def setNumThreads(n):
    """No-op thread concurrency limit."""
    pass

def cvtColor(src, code):
    """Color space conversion between RGB, BGR, and Grayscale."""
    if code in (COLOR_RGB2BGR, COLOR_BGR2RGB):
        return src[..., ::-1]
    elif code == COLOR_BGR2GRAY:
        gray = 0.114 * src[..., 0] + 0.587 * src[..., 1] + 0.299 * src[..., 2]
        return np.clip(np.round(gray), 0, 255).astype(np.uint8)
    elif code == COLOR_RGB2GRAY:
        gray = 0.299 * src[..., 0] + 0.587 * src[..., 1] + 0.114 * src[..., 2]
        return np.clip(np.round(gray), 0, 255).astype(np.uint8)
    elif code in (COLOR_GRAY2BGR, COLOR_GRAY2RGB):
        return np.repeat(src[..., None], 3, axis=-1)
    raise ValueError(f"Unsupported cvtColor code: {code}")

def GaussianBlur(src, ksize, sigmaX, sigmaY=0, borderType=BORDER_REPLICATE):
    """Gaussian blur filter."""
    if sigmaX == 0 and ksize[0] > 0:
        sigmaX = 0.3 * ((ksize[0] - 1) * 0.5 - 1) + 0.8
    sy = sigmaX if sigmaY == 0 else sigmaY
    mode = 'nearest' if borderType == BORDER_REPLICATE else 'constant'
    if src.ndim == 2:
        return scipy.ndimage.gaussian_filter(src, [sy, sigmaX], mode=mode)
    return scipy.ndimage.gaussian_filter(src, [sy, sigmaX, 0], mode=mode)

def resize(src, dsize, interpolation=INTER_LINEAR):
    """Image resizing with nearest, linear, cubic, or area interpolation."""
    w, h = dsize
    resample = Image.Resampling.BILINEAR
    if interpolation == INTER_AREA:
        resample = Image.Resampling.BOX
    elif interpolation == INTER_CUBIC:
        resample = Image.Resampling.BICUBIC
    elif interpolation == INTER_NEAREST:
        resample = Image.Resampling.NEAREST

    if src.ndim == 3 and src.dtype == np.float32:
        out = np.empty((h, w, src.shape[2]), dtype=np.float32)
        for c in range(src.shape[2]):
            out[:, :, c] = np.array(
                Image.fromarray(src[:, :, c], mode='F').resize((w, h), resample=resample),
                dtype=np.float32
            )
        return out
    if src.ndim == 2 and src.dtype == np.float32:
        return np.array(
            Image.fromarray(src, mode='F').resize((w, h), resample=resample),
            dtype=np.float32
        )

    pil_img = Image.fromarray(src)
    return np.array(pil_img.resize((w, h), resample=resample), dtype=src.dtype)

def flip(src, flipCode):
    """Flips image horizontally, vertically, or both."""
    if flipCode == 0:
        return src[::-1, ...]
    elif flipCode > 0:
        return src[:, ::-1, ...]
    return src[::-1, ::-1, ...]

def getRotationMatrix2D(center, angle, scale):
    """Calculates an affine matrix of 2D rotation."""
    cx, cy = center
    rad = np.radians(angle)
    alpha = scale * np.cos(rad)
    beta = scale * np.sin(rad)
    return np.array([
        [alpha, beta, (1 - alpha) * cx - beta * cy],
        [-beta, alpha, beta * cx + (1 - alpha) * cy]
    ], dtype=np.float32)

def getPerspectiveTransform(src, dst):
    """Calculates a perspective transform from 4 pairs of the corresponding points."""
    A, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    h = np.linalg.solve(np.array(A, dtype=np.float64), np.array(b, dtype=np.float64))
    return np.array([[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]], dtype=np.float32)

def warpPerspective(img, M, dsize, flags=INTER_LINEAR, borderMode=BORDER_REPLICATE):
    """Applies a perspective transformation to an image."""
    w, h = dsize
    Minv = np.linalg.inv(M)
    ys, xs = np.indices((h, w), dtype=np.float32)
    dst_coords = np.vstack([xs.ravel(), ys.ravel(), np.ones(h * w, dtype=np.float32)])
    src_coords = Minv @ dst_coords
    src_x = (src_coords[0] / src_coords[2]).reshape((h, w))
    src_y = (src_coords[1] / src_coords[2]).reshape((h, w))
    mode = 'nearest' if borderMode == BORDER_REPLICATE else 'constant'
    if img.ndim == 2:
        return scipy.ndimage.map_coordinates(img, [src_y, src_x], order=1, mode=mode)
    out = np.empty((h, w, img.shape[2]), dtype=img.dtype)
    for c in range(img.shape[2]):
        out[:, :, c] = scipy.ndimage.map_coordinates(img[:, :, c], [src_y, src_x], order=1, mode=mode)
    return out

def warpAffine(img, M, dsize, flags=INTER_LINEAR, borderMode=BORDER_CONSTANT, borderValue=0):
    """Applies an affine transformation to an image."""
    w, h = dsize
    M3 = np.eye(3, dtype=np.float32)
    M3[:2, :] = M
    Minv = np.linalg.inv(M3)
    ys, xs = np.indices((h, w), dtype=np.float32)
    dst_coords = np.vstack([xs.ravel(), ys.ravel(), np.ones(h * w, dtype=np.float32)])
    src_coords = Minv @ dst_coords
    src_x = (src_coords[0] / src_coords[2]).reshape((h, w))
    src_y = (src_coords[1] / src_coords[2]).reshape((h, w))
    mode = 'nearest' if borderMode == BORDER_REPLICATE else 'constant'
    if img.ndim == 2:
        cval = borderValue if isinstance(borderValue, (int, float)) else borderValue[0]
        return scipy.ndimage.map_coordinates(img, [src_y, src_x], order=1, mode=mode, cval=cval)
    out = np.empty((h, w, img.shape[2]), dtype=img.dtype)
    for c in range(img.shape[2]):
        cval = borderValue[c] if hasattr(borderValue, '__getitem__') else borderValue
        out[:, :, c] = scipy.ndimage.map_coordinates(img[:, :, c], [src_y, src_x], order=1, mode=mode, cval=cval)
    return out

def remap(src, map1, map2, interpolation=INTER_LINEAR, borderMode=BORDER_REPLICATE, borderValue=0):
    """Applies a generic geometrical transformation to an image."""
    mode = 'nearest' if borderMode == BORDER_REPLICATE else 'constant'
    cval = borderValue if isinstance(borderValue, (int, float)) else borderValue[0]
    if src.ndim == 2:
        return scipy.ndimage.map_coordinates(src, [map2, map1], order=1, mode=mode, cval=cval)
    out = np.empty((map1.shape[0], map1.shape[1], src.shape[2]), dtype=src.dtype)
    for c in range(src.shape[2]):
        out[:, :, c] = scipy.ndimage.map_coordinates(src[:, :, c], [map2, map1], order=1, mode=mode, cval=cval)
    return out

def circle(img, center, radius, color, thickness=1, lineType=LINE_AA):
    """Draws a circle on the image in-place."""
    pil_img = Image.fromarray(img)
    draw = ImageDraw.Draw(pil_img)
    col = tuple(color) if hasattr(color, '__iter__') else (color, color, color)
    cx, cy = center
    draw.ellipse([(cx - radius, cy - radius), (cx + radius, cy + radius)], outline=col, width=thickness)
    img[:] = np.array(pil_img)
    return img

def putText(img, text, org, fontFace, fontScale, color, thickness=1, lineType=LINE_AA):
    """Draws a text string on the image in-place."""
    pil_img = Image.fromarray(img)
    draw = ImageDraw.Draw(pil_img)
    col = tuple(color) if hasattr(color, '__iter__') else (color, color, color)
    draw.text(org, text, fill=col)
    img[:] = np.array(pil_img)
    return img

def line(img, pt1, pt2, color, thickness=1, lineType=LINE_AA):
    """Draws a line segment connecting two points in-place."""
    pil_img = Image.fromarray(img)
    draw = ImageDraw.Draw(pil_img)
    col = tuple(color) if hasattr(color, '__iter__') else (color, color, color)
    draw.line([pt1, pt2], fill=col, width=thickness)
    img[:] = np.array(pil_img)
    return img

def addWeighted(src1, alpha, src2, beta, gamma):
    """Calculates the weighted sum of two arrays."""
    res = src1.astype(np.float32) * alpha + src2.astype(np.float32) * beta + gamma
    return np.clip(res, 0, 255).astype(src1.dtype)

def filter2D(src, ddepth, kernel, borderType=BORDER_REPLICATE):
    """Convolves an image with the kernel."""
    mode = 'nearest' if borderType == BORDER_REPLICATE else 'constant'
    if src.ndim == 2:
        return scipy.ndimage.convolve(src, kernel, mode=mode)
    out = np.empty_like(src)
    for c in range(src.shape[2]):
        out[:, :, c] = scipy.ndimage.convolve(src[:, :, c], kernel, mode=mode)
    return out

def boxFilter(src, ddepth, ksize, normalize=True, borderType=BORDER_CONSTANT):
    """Blurs an image using the box filter."""
    kw, kh = ksize
    mode = 'constant' if borderType == BORDER_CONSTANT else 'nearest'
    res = scipy.ndimage.uniform_filter(src, size=(kh, kw), mode=mode)
    if not normalize:
        res = res * (kw * kh)
    return res

def imencode(ext, img, params=None):
    """Encodes an image into a memory buffer."""
    q = 95
    if params:
        for i in range(0, len(params), 2):
            if params[i] == IMWRITE_JPEG_QUALITY:
                q = int(params[i + 1])
    bio = io.BytesIO()
    pil_img = Image.fromarray(img[:, :, ::-1] if img.ndim == 3 else img)
    pil_img.save(bio, format='JPEG', quality=q)
    return True, np.frombuffer(bio.getvalue(), dtype=np.uint8)

def imdecode(buf, flags=IMREAD_COLOR):
    """Reads an image from a buffer in memory."""
    bio = io.BytesIO(buf.tobytes() if hasattr(buf, 'tobytes') else bytes(buf))
    pil_img = Image.open(bio)
    if flags == IMREAD_GRAYSCALE:
        return np.array(pil_img.convert('L'))
    rgb = np.array(pil_img.convert('RGB'))
    return rgb[:, :, ::-1]
