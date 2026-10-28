"""Translate ACP context without granting it additional tool authority."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from acp import RequestError
from acp.schema import ResourceContentBlock, TextContentBlock

__all__ = ["prompt_text"]


def prompt_text(blocks: list[object], cwd: Path) -> str:
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
                if not path.is_relative_to(cwd):
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
