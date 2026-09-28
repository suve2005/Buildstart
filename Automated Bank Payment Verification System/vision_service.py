import io

import cv2
import numpy as np
from PIL import Image

BLUR_THRESHOLDS = {"DIGITAL": 50.0, "PHYSICAL_SLIP": 100.0, "ATM_RECEIPT": 100.0}  # tune on real samples
MAX_PIXELS = 25_000_000  # protection against decompression bombs


def _decode(file_bytes: bytes):
    # Read dimensions from the header only (no pixel decode) BEFORE decoding the image
    try:
        w, h = Image.open(io.BytesIO(file_bytes)).size
    except Exception:
        return None
    if w * h > MAX_PIXELS:
        return None
    return cv2.imdecode(np.frombuffer(file_bytes, np.uint8), cv2.IMREAD_COLOR)


def assess_image_quality(file_bytes: bytes, category: str = "PHYSICAL_SLIP") -> dict:
    image = _decode(file_bytes)
    if image is None:
        return {"is_clear": False, "reason": "invalid_image_format"}

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    # Normalize resolution before calculating variance to ensure consistent scoring
    gray = cv2.resize(gray, (1000, int(h * 1000 / w)))
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()

    if variance < BLUR_THRESHOLDS.get(category, 100.0):
        return {"is_clear": False, "reason": "image_too_blurry", "score": variance}
    return {"is_clear": True, "reason": "legible", "score": variance}


def categorize_image(file_bytes: bytes) -> str:
    """Heuristic first pass based on color saturation and aspect ratio."""
    image = _decode(file_bytes)
    if image is None:
        return "PHYSICAL_SLIP"

    h, w = image.shape[:2]
    saturation = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 1].mean()

    if saturation < 25:
        return "ATM_RECEIPT"
    if h / w > 1.9 and saturation > 40:
        return "DIGITAL"
    return "PHYSICAL_SLIP"


def _ela_penalty(image) -> float:
    """Error Level Analysis for digital manipulation detection. Constants are guesses: calibrate on real slips."""
    ok, enc = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    recompressed = cv2.imdecode(enc, cv2.IMREAD_COLOR)
    diff = cv2.cvtColor(cv2.absdiff(image, recompressed), cv2.COLOR_BGR2GRAY).astype(np.float32)

    B = 32
    h, w = (diff.shape[0] // B) * B, (diff.shape[1] // B) * B
    if h == 0 or w == 0:
        return 0.0
    blocks = diff[:h, :w].reshape(h // B, B, w // B, B).mean(axis=(1, 3))

    # Floor of 1.0 stops flat screenshots (median ~ 0) from producing huge ratios
    ratio = np.percentile(blocks, 99) / max(np.median(blocks), 1.0)
    return float(min(40.0, max(0.0, (ratio - 4.0) * 5.0)))


def detect_visual_fraud(file_bytes: bytes, category: str) -> dict:
    image = _decode(file_bytes)
    if image is None:
        return {"is_fraudulent": False, "confidence_penalty": 50.0}

    penalty = _ela_penalty(image) if category == "DIGITAL" else 0.0  # physical checks still TODO
    return {"is_fraudulent": False, "confidence_penalty": penalty}