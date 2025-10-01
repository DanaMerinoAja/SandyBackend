# preprocess/image_ops.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
from io import BytesIO

from PIL import Image, ImageOps, ImageFilter
import pytesseract
import cv2
import numpy as np

@dataclass
class PreprocessMeta:
    steps: List[str] = field(default_factory=list)
    exif_applied: bool = False
    osd_angle: Optional[int] = None
    osd_conf: Optional[float] = None
    rotated_final: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None

def _pil_to_cv2(img: Image.Image) -> np.ndarray:
    arr = np.array(img.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

def _cv2_to_pil(img_cv: np.ndarray) -> Image.Image:
    rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)

def _apply_exif(img: Image.Image, meta: PreprocessMeta) -> Image.Image:
    before = (img.width, img.height)
    img2 = ImageOps.exif_transpose(img)
    meta.exif_applied = (img2.size != before)
    if meta.exif_applied:
        meta.steps.append("exif_transpose")
    return img2

def _osd_orientation(img: Image.Image) -> Tuple[Optional[int], Optional[float]]:
    """
    Usa OSD de Tesseract para estimar orientación (0/90/180/270) y confianza.
    Devuelve (angle, conf) o (None, None) si falla.
    """
    try:
        osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
        angle = int(osd.get("rotate", 0))
        conf = float(osd.get("orientation_confidence", 0.0))
        return angle, conf
    except Exception:
        return None, None

def _normalize_size(img_cv: np.ndarray, max_side: int = 1800) -> np.ndarray:
    h, w = img_cv.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        img_cv = cv2.resize(img_cv, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img_cv

def _basic_enhance(img: Image.Image, meta: PreprocessMeta) -> Image.Image:
    # Filtro leve + sharpen
    img2 = img.convert("L")
    img2 = img2.filter(ImageFilter.MedianFilter(size=3))
    img2 = img2.filter(ImageFilter.UnsharpMask(radius=1.0, percent=150, threshold=3))
    meta.steps.append("enhance_basic")
    return img2

def _adaptive_binarize(img_cv: np.ndarray, meta: PreprocessMeta) -> np.ndarray:
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY) if len(img_cv.shape) == 3 else img_cv
    bin_img = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 15
    )
    meta.steps.append("adaptive_binarize")
    return cv2.cvtColor(bin_img, cv2.COLOR_GRAY2BGR)

def _deskew(img_cv: np.ndarray, meta: PreprocessMeta, max_angle: float = 5.0) -> np.ndarray:
    # Deskew rápido basado en umbral + minAreaRect (solo pequeños ángulos)
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(th == 0))
    if coords.size == 0:
        return img_cv
    rect = cv2.minAreaRect(coords)
    angle = rect[-1]
    if angle < -45:
        angle = 90 + angle
    if abs(angle) < 0.5 or abs(angle) > max_angle:
        return img_cv
    (h, w) = img_cv.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    rotated = cv2.warpAffine(img_cv, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    meta.steps.append(f"deskew_{angle:.2f}")
    return rotated

def rotate_by_angle(img: Image.Image, angle: int, meta: Optional[PreprocessMeta] = None) -> Image.Image:
    """
    Rota imagen en múltiplos de 90 (0, 90, 180, 270).
    """
    if angle % 360 == 0:
        return img
    k = (angle // 90) % 4
    img2 = img.rotate(-angle, expand=True) if angle not in (90, 180, 270) else img.transpose([Image.ROTATE_270, Image.ROTATE_180, Image.ROTATE_90][k-1])
    if meta:
        meta.rotated_final = (meta.rotated_final or 0) + angle
        meta.steps.append(f"rotate_{angle}")
    return img2

def process_image(image_bytes: bytes, use_gpt_orientation: bool = False) -> Tuple[bytes, PreprocessMeta]:
    """
    Pipeline:
      1) EXIF transpose
      2) OSD (pytesseract) → rotación 0/90/180/270 si conf >= umbral
      3) Realce básico + binarización adaptativa
      4) Deskew leve (<= ~5°)
    Retorna bytes PNG y metadatos (para logging).
    """
    meta = PreprocessMeta()
    img = Image.open(BytesIO(image_bytes))
    meta.width, meta.height = img.size

    # 1) EXIF
    img = _apply_exif(img, meta)

    # 2) OSD orientación (solo si la imagen es razonable)
    angle, conf = _osd_orientation(img)
    meta.osd_angle, meta.osd_conf = angle, conf
    if angle is not None and conf is not None and conf >= 3.0 and angle in (0, 90, 180, 270):
        if angle != 0:
            img = rotate_by_angle(img, angle, meta)

    # 3) Enhancements + 4) Deskew
    img = _basic_enhance(img, meta)
    cv = _pil_to_cv2(img)
    cv = _normalize_size(cv)
    cv = _adaptive_binarize(cv, meta)
    cv = _deskew(cv, meta)
    out = _cv2_to_pil(cv)

    # salida png
    buf = BytesIO()
    out.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), meta
