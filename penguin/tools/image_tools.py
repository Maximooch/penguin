"""General image-ingest tools for multimodal model turns."""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image

from penguin.utils.path_utils import enforce_allowed_path


SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP", "BMP", "TIFF"}


class ReadImageTool:
    """Validate an image path and return model-visible artifact metadata."""

    def execute(
        self,
        path: str,
        prompt: Optional[str] = None,
        max_dim: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not path:
            return {"error": "path is required"}

        try:
            image_path = enforce_allowed_path(Path(path), root_pref="auto")
        except Exception as exc:
            return {"error": f"Image path is outside allowed roots: {exc}"}

        if not image_path.exists():
            return {"error": f"Image does not exist: {image_path}"}
        if not image_path.is_file():
            return {"error": f"Image path is not a file: {image_path}"}

        try:
            with Image.open(image_path) as image:
                image.verify()
            with Image.open(image_path) as image:
                width, height = image.size
                image_format = image.format or "UNKNOWN"
        except Exception as exc:
            return {"error": f"Unable to read image: {exc}"}

        if image_format.upper() not in SUPPORTED_IMAGE_FORMATS:
            return {"error": f"Unsupported image format: {image_format}"}

        mime_type = mimetypes.guess_type(str(image_path))[0]
        if not mime_type or not mime_type.startswith("image/"):
            mime_type = f"image/{image_format.lower()}"

        return {
            "result": "Image loaded",
            "filepath": str(image_path),
            "prompt": prompt or "What can you see in this image?",
            "artifact": {
                "type": "image",
                "mime_type": mime_type,
                "path": str(image_path),
                "image_path": str(image_path),
                "width": width,
                "height": height,
                "format": image_format,
                "max_dim": max_dim,
            },
            "width": width,
            "height": height,
            "format": image_format,
            "mime_type": mime_type,
            "size_bytes": image_path.stat().st_size,
        }
