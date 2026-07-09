from __future__ import annotations

import os
from typing import Any, Dict

try:
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover - exercised when dependency is unavailable
    Image = None


def analyze_image(image_path: str | None = None) -> Dict[str, Any]:
    if not image_path or not os.path.exists(image_path):
        return {
            "available": False,
            "summary": "No image uploaded.",
            "format": None,
            "size": None,
            "dimensions": None,
            "caption": "No image available for analysis.",
            "supports_message": False,
        }

    if Image is None:
        return {
            "available": True,
            "summary": "Image file detected but Pillow is not installed.",
            "format": os.path.splitext(image_path)[1].lstrip("."),
            "size": os.path.getsize(image_path),
            "dimensions": None,
            "caption": "Basic file analysis only.",
            "supports_message": True,
        }

    with Image.open(image_path) as img:
        img.load()
        width, height = img.size
        mode = img.mode
        fmt = img.format or os.path.splitext(image_path)[1].lstrip(".")
        filename = os.path.basename(image_path)
        caption = f"{filename} is a {fmt.upper()} image with {width}x{height} pixels."

        return {
            "available": True,
            "summary": f"Image resolved as {fmt.upper()} in {mode} mode.",
            "format": fmt,
            "size": os.path.getsize(image_path),
            "dimensions": {"width": width, "height": height},
            "caption": caption,
            "supports_message": True,
        }
