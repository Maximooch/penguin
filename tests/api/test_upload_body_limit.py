"""Verify the upload boundary with the real FastAPI multipart parser."""

from fastapi import FastAPI, File, UploadFile
from fastapi.testclient import TestClient

from penguin.web.middleware.upload_limit import (
    MULTIPART_OVERHEAD_BYTES,
    UploadBodyLimitMiddleware,
)


def test_upload_request_limit(monkeypatch):
    monkeypatch.setenv("PENGUIN_MAX_UPLOAD_BYTES", "1024")
    app = FastAPI()
    app.add_middleware(UploadBodyLimitMiddleware)
    parsed = []

    @app.post("/api/v1/upload")
    async def upload(file: UploadFile = File(...)):
        parsed.append(await file.read())
        return {"accepted": True}

    client = TestClient(app)
    assert client.post(
        "/api/v1/upload", files={"file": ("image.png", b"image", "image/png")}
    ).status_code == 200

    def should_not_read():
        raise AssertionError("declared oversize body should not be read")
        yield b""  # pragma: no cover

    headers = {"content-type": "multipart/form-data; boundary=test"}
    response = client.post(
        "/api/v1/upload",
        headers={**headers, "content-length": str(1025 + MULTIPART_OVERHEAD_BYTES)},
        content=should_not_read(),
    )
    assert response.status_code == 413

    def streamed():
        yield b'--test\r\nContent-Disposition: form-data; name="file"; filename="image.png"\r\n\r\n'
        yield b"a" * (1024 + MULTIPART_OVERHEAD_BYTES)
        yield b"\r\n--test--\r\n"

    response = client.post("/api/v1/upload", headers=headers, content=streamed())
    assert response.status_code == 413
    assert parsed == [b"image"]
