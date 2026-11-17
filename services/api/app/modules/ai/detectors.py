"""Face detection for redaction. Runs locally with OpenCV, so no photo leaves the system for it."""

from functools import lru_cache
from typing import Protocol

import cv2
import numpy as np
from PIL import Image

from app.modules.ai.schemas import Region

Box = tuple[int, int, int, int]  # x, y, width, height in pixels


class FaceDetector(Protocol):
    name: str
    version: str

    def detect(self, image: Image.Image) -> list[Region]: ...


@lru_cache
def _cascade(filename: str) -> cv2.CascadeClassifier:
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + filename)  # type: ignore[attr-defined]
    if cascade.empty():
        raise RuntimeError(f"OpenCV cascade {filename} is missing.")
    return cascade


def _overlap(a: Box, b: Box) -> float:
    """Intersection over the smaller box: 1 when one box lies inside the other."""
    width = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    height = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    return width * height / min(a[2] * a[3], b[2] * b[3])


class OpenCvFaceDetector:
    """Haar cascades: frontal faces, and profiles facing either way.

    Known limits: misses small, tilted, partly hidden or turned-away faces, and sometimes
    marks patterns (wallpaper, artwork) as faces. It gives no calibrated confidence.
    """

    name = "opencv-haar-faces"
    version = f"opencv-{cv2.__version__}"

    def detect(self, image: Image.Image) -> list[Region]:
        gray = np.asarray(image.convert("L"))
        height, width = gray.shape
        side = max(24, round(min(width, height) * 0.03))
        size = (side, side)
        boxes: list[Box] = []
        for filename, flipped in (
            ("haarcascade_frontalface_default.xml", False),
            ("haarcascade_profileface.xml", False),
            ("haarcascade_profileface.xml", True),
        ):
            source = cv2.flip(gray, 1) if flipped else gray
            found = _cascade(filename).detectMultiScale(
                source, scaleFactor=1.1, minNeighbors=5, minSize=size
            )
            for x, y, w, h in found:
                box = (width - int(x) - int(w) if flipped else int(x), int(y), int(w), int(h))
                if all(_overlap(box, kept) < 0.5 for kept in boxes):
                    boxes.append(box)
        return [
            Region(
                category="face",
                box=(x / width, y / height, w / width, h / height),
                detector=self.name,
            )
            for x, y, w, h in boxes
        ]
