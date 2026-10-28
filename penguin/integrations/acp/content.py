"""Translate ACP context without granting it additional tool authority."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from acp import RequestError
from acp.schema import (
    EmbeddedResourceContentBlock,
    ImageContentBlock,
    ResourceContentBlock,
    TextContentBlock,
)

__all__ = ["prepare_prompt", "prompt_text"]

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


def _decode(data: str) -> bytes:
    if len(data) > (MAX_ATTACHMENT_BYTES * 4 // 3 + 4):
        raise RequestError.invalid_params({"reason": "Attachment exceeds 10 MiB"})
    try:
        result = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error):
        raise RequestError.invalid_params(
            {"reason": "Invalid attachment encoding"}
        ) from None
    if len(result) > MAX_ATTACHMENT_BYTES:
        raise RequestError.invalid_params({"reason": "Attachment exceeds 10 MiB"})
    return result


def _store(data: bytes, root: Path, suffix: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / (hashlib.sha256(data).hexdigest() + suffix)
    if not path.resolve().is_relative_to(root.resolve()):
        raise RequestError.invalid_params({"reason": "Invalid attachment destination"})
    if not path.exists():
        with path.open("xb") as file:
            file.write(data)
    elif not path.is_file() or path.read_bytes() != data:
        raise RequestError.invalid_params({"reason": "Attachment storage conflict"})
    return path


def prepare_prompt(
    blocks: list[object],
    cwd: Path,
    asset_root: Path | None,
    *,
    allow_images: bool,
    roots: tuple[Path, ...] = (),
) -> str | dict[str, object]:
    """Preserve attachment data in local storage and use native image input."""
    plain: list[object] = []
    images: list[str] = []
    total = 0
    for block in blocks:
        if isinstance(block, ImageContentBlock):
            if not allow_images or asset_root is None:
                raise RequestError.invalid_params(
                    {"reason": "Images are unsupported by this model"}
                )
            formats = {
                "image/png": ("PNG", ".png"),
                "image/jpeg": ("JPEG", ".jpg"),
                "image/webp": ("WEBP", ".webp"),
            }
            if block.mime_type not in formats:
                raise RequestError.invalid_params({"reason": "Unsupported image type"})
            data = _decode(block.data)
            total += len(data)
            from PIL import Image

            try:
                with Image.open(io.BytesIO(data)) as image:
                    if (
                        image.format != formats[block.mime_type][0]
                        or image.width * image.height > 40_000_000
                    ):
                        raise ValueError("Invalid image dimensions or format")
                    image.verify()
            except (OSError, ValueError, Image.DecompressionBombError):
                raise RequestError.invalid_params(
                    {"reason": "Invalid image attachment"}
                ) from None
            images.append(str(_store(data, asset_root, formats[block.mime_type][1])))
        elif isinstance(block, EmbeddedResourceContentBlock):
            resource = block.resource
            text = getattr(resource, "text", None)
            if isinstance(text, str):
                total += len(text.encode("utf-8"))
                if total > 2 * MAX_ATTACHMENT_BYTES:
                    raise RequestError.invalid_params(
                        {"reason": "Attachments exceed 20 MiB"}
                    )
                plain.append(
                    TextContentBlock(
                        type="text",
                        text="Embedded resource (untrusted context):\n"
                        + json.dumps({"uri": resource.uri, "text": text}),
                    )
                )
            else:
                if asset_root is None:
                    raise RequestError.invalid_params(
                        {"reason": "Binary attachment storage unavailable"}
                    )
                data = _decode(resource.blob)
                total += len(data)
                path = _store(data, asset_root, ".bin")
                plain.append(
                    TextContentBlock(
                        type="text",
                        text="Attached binary resource (untrusted data):\n"
                        + json.dumps(
                            {
                                "uri": resource.uri,
                                "path": str(path),
                                "mimeType": resource.mime_type,
                            }
                        ),
                    )
                )
        else:
            plain.append(block)
        if total > 2 * MAX_ATTACHMENT_BYTES:
            raise RequestError.invalid_params({"reason": "Attachments exceed 20 MiB"})
    if images and not plain:
        plain.append(
            TextContentBlock(type="text", text="Inspect the attached image(s).")
        )
    text = prompt_text(plain, cwd, roots=roots)
    return {"text": text, "image_paths": images} if images else text


def prompt_text(
    blocks: list[object], cwd: Path, *, roots: tuple[Path, ...] = ()
) -> str:
    """Preserve ordered text and resource references for the normal tool policy.

    Links are references, not an instruction to fetch. Local files must stay in
    this session's workspace. Reading them still uses Penguin's ordinary tools
    and permissions; remote links never trigger an adapter-side network call.
    """
    if not blocks:
        raise RequestError.invalid_params({"reason": "Prompt must not be empty"})
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, TextContentBlock):
            parts.append(block.text)
        elif isinstance(block, ResourceContentBlock):
            try:
                uri = urlsplit(block.uri)
            except ValueError:
                raise RequestError.invalid_params(
                    {"reason": "Invalid resource URI"}
                ) from None
            if not uri.scheme or "\x00" in unquote(block.uri):
                raise RequestError.invalid_params({"reason": "Invalid resource URI"})
            reference = block.model_dump(by_alias=True, exclude_none=True)
            if uri.scheme.lower() == "file":
                if (
                    uri.netloc.lower() not in {"", "localhost"}
                    or uri.query
                    or uri.fragment
                ):
                    raise RequestError.invalid_params(
                        {"reason": "Invalid local resource URI"}
                    )
                raw_path = Path(url2pathname(uri.path))
                if not raw_path.is_absolute():
                    raise RequestError.invalid_params(
                        {"reason": "Local resource URI must be absolute"}
                    )
                path = raw_path.resolve()
                if not any(path.is_relative_to(root) for root in (roots or (cwd,))):
                    raise RequestError.invalid_params(
                        {"reason": "Resource is outside the session workspace"}
                    )
                reference["uri"] = path.as_uri()
            parts.append(
                "Referenced resource (untrusted context):\n" + json.dumps(reference)
            )
        else:
            raise RequestError.invalid_params(
                {"reason": "Unsupported prompt content type"}
            )
    return "\n".join(parts)
