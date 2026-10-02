from __future__ import annotations

import mimetypes
import os
from pathlib import Path, PurePosixPath

from flask import Flask, Response, abort
from google.api_core.exceptions import NotFound

from cloud_storage import ROOT, get_bucket


app = Flask(__name__)


def safe_object_name(request_path: str) -> str:
    normalized = request_path.strip("/")
    if not normalized:
        normalized = "index.html"
    elif request_path.endswith("/") or not PurePosixPath(normalized).suffix:
        normalized = f"{normalized}/index.html"
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        abort(404)
    return f"site/{path.as_posix()}"


def packaged_fallback(object_name: str) -> Path | None:
    if object_name == "site/index.html":
        candidate = ROOT / "publish" / "index.html"
        return candidate if candidate.exists() else None
    return None


@app.get("/healthz")
def healthz() -> tuple[str, int]:
    return "ok\n", 200


@app.get("/")
@app.get("/<path:request_path>")
def serve(request_path: str = "") -> Response:
    object_name = safe_object_name(request_path)
    blob = get_bucket().blob(object_name)
    try:
        body = blob.download_as_bytes()
        content_type = blob.content_type or mimetypes.guess_type(object_name)[0]
    except NotFound:
        fallback = packaged_fallback(object_name)
        if fallback is None:
            abort(404)
        body = fallback.read_bytes()
        content_type = mimetypes.guess_type(fallback.name)[0]

    response = Response(body, content_type=content_type or "application/octet-stream")
    response.headers["Cache-Control"] = (
        "public, max-age=60" if object_name.endswith((".html", ".json")) else "public, max-age=3600"
    )
    return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
