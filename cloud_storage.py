from __future__ import annotations

import mimetypes
import os
from pathlib import Path, PurePosixPath

from google.api_core.exceptions import NotFound
from google.cloud import storage


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PUBLISH_DIR = ROOT / "publish"

STATE_FILES = (
    "latest.json",
    "history.json",
    "published_sessions.json",
)


def bucket_name() -> str:
    value = os.environ.get("STATE_BUCKET", "").strip()
    if not value:
        raise RuntimeError("STATE_BUCKET is required")
    return value


def get_bucket() -> storage.Bucket:
    return storage.Client().bucket(bucket_name())


def _safe_relative(value: str) -> Path:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe object path: {value}")
    return Path(*path.parts)


def restore_state() -> int:
    bucket = get_bucket()
    restored = 0
    try:
        blobs = list(bucket.list_blobs(prefix="state/"))
    except NotFound:
        return 0

    for blob in blobs:
        relative_name = blob.name.removeprefix("state/")
        if not relative_name or relative_name.endswith("/"):
            continue
        relative = _safe_relative(relative_name)
        if relative.parts[0] != "cache" and relative.as_posix() not in STATE_FILES:
            continue
        destination = DATA_DIR / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(destination)
        restored += 1
    print(f"Restored {restored} state objects from gs://{bucket.name}/state/", flush=True)
    return restored


def save_state() -> int:
    bucket = get_bucket()
    sources = [DATA_DIR / name for name in STATE_FILES]
    cache_dir = DATA_DIR / "cache"
    if cache_dir.exists():
        sources.extend(path for path in cache_dir.rglob("*") if path.is_file())

    saved = 0
    for source in sources:
        if not source.exists():
            continue
        relative = source.relative_to(DATA_DIR).as_posix()
        bucket.blob(f"state/{relative}").upload_from_filename(source)
        saved += 1
    print(f"Saved {saved} state objects to gs://{bucket.name}/state/", flush=True)
    return saved


def _upload_site_file(source: Path, object_name: str) -> None:
    content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    get_bucket().blob(object_name).upload_from_filename(source, content_type=content_type)


def publish_site() -> int:
    index_path = PUBLISH_DIR / "index.html"
    latest_path = DATA_DIR / "latest.json"
    if not index_path.exists() or not latest_path.exists():
        raise RuntimeError("Dashboard output is incomplete")

    uploads: list[tuple[Path, str]] = [
        (index_path, "site/index.html"),
        (latest_path, "site/latest.json"),
    ]
    leaders_dir = ROOT / "leader-watch" / "public"
    if leaders_dir.exists():
        uploads.extend(
            (path, f"site/leaders/{path.relative_to(leaders_dir).as_posix()}")
            for path in leaders_dir.rglob("*")
            if path.is_file()
        )

    for source, object_name in uploads:
        _upload_site_file(source, object_name)
    print(f"Published {len(uploads)} objects to gs://{bucket_name()}/site/", flush=True)
    return len(uploads)
