from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

MIRROR_REVISION = "8e9c6b569122fb20668f5da3b0f3970a853fc5d8"
MIRROR_BASE = (
    "https://huggingface.co/datasets/recommender-system/steam-review-and-bundle-dataset"
    f"/resolve/{MIRROR_REVISION}"
)
MIRROR_API = (
    "https://huggingface.co/api/datasets/recommender-system/steam-review-and-bundle-dataset"
    f"/tree/{MIRROR_REVISION}?recursive=true&expand=true"
)
PUBLISHER_BASE = "https://mcauleylab.ucsd.edu/public_datasets/data/steam"
FILES = ("steam_games.json.gz", "steam_reviews.json.gz")


@dataclass(frozen=True)
class DownloadEvidence:
    filename: str
    source: str
    requested_url: str
    redirect_destination: str
    revision: str | None
    bytes: int
    sha256: str
    upstream_sha256: str | None
    upstream_digest_source: str | None
    etag: str | None
    last_modified: str | None
    downloaded_at: str
    publisher_fallback_reason: str | None = None


def source_url(filename: str, source: str) -> tuple[str, str | None]:
    if filename not in FILES:
        raise ValueError(f"Unsupported dataset file: {filename}")
    if source == "publisher":
        return f"{PUBLISHER_BASE}/{filename}", None
    if source == "mirror":
        return f"{MIRROR_BASE}/{filename}", MIRROR_REVISION
    raise ValueError("source must be 'publisher' or 'mirror'")


def _request(url: str, method: str = "GET", headers: dict[str, str] | None = None):
    request_headers = {"User-Agent": "game-discovery-ml/0.1 research-data-downloader"}
    request_headers.update(headers or {})
    return urlopen(Request(url, method=method, headers=request_headers), timeout=60)


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _read_state(state_path: Path) -> dict[str, str] | None:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return state if isinstance(state, dict) else None


def _write_state(state_path: Path, state: dict[str, str]) -> None:
    temp = state_path.with_suffix(state_path.suffix + ".tmp")
    temp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    os.replace(temp, state_path)


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_gzip(path: Path) -> None:
    with gzip.open(path, "rb") as stream:
        for _ in iter(lambda: stream.read(1024 * 1024), b""):
            pass


def _mirror_file_metadata(filename: str) -> tuple[str | None, int | None]:
    with _request(MIRROR_API) as response:
        entries = json.loads(response.read())
    item = next(
        (
            entry
            for entry in entries
            if entry.get("path") == filename and entry.get("type") == "file"
        ),
        None,
    )
    if item is None:
        raise RuntimeError(f"Pinned mirror metadata has no file entry for {filename}")
    lfs = item.get("lfs") or {}
    upstream_sha = lfs.get("oid")
    if upstream_sha and not re.fullmatch(r"[0-9a-fA-F]{64}", upstream_sha):
        raise RuntimeError(f"Unexpected upstream LFS SHA-256 for {filename}: {upstream_sha}")
    size = lfs.get("size", item.get("size"))
    return upstream_sha.lower() if upstream_sha else None, int(size) if size is not None else None


def verify_download(
    path: Path,
    expected_sha256: str,
    *,
    expected_bytes: int | None = None,
    check_sha256: bool = True,
    check_gzip: bool = True,
) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    if expected_bytes is not None and path.stat().st_size != expected_bytes:
        raise RuntimeError(f"File size differs from source manifest for {path}")
    if check_sha256:
        actual = _digest_file(path)
        if actual != expected_sha256:
            raise RuntimeError(f"File hash differs from source manifest for {path}: {actual}")
    if check_gzip:
        _verify_gzip(path)


def _stream_to_partial(
    url: str, partial: Path, state_path: Path
) -> tuple[int, str, str | None, str | None]:
    with _request(url, method="HEAD") as head:
        expected_size = (
            int(head.headers["Content-Length"]) if head.headers.get("Content-Length") else None
        )
        expected_etag = head.headers.get("ETag")
        last_modified = head.headers.get("Last-Modified")
        redirect_destination = _safe_url(head.url)

    state = _read_state(state_path)
    offset = partial.stat().st_size if partial.exists() else 0
    recorded_bytes = int(state.get("bytes_written", "-1")) if state is not None else -1
    valid_resume = (
        state is not None
        and state.get("url") == url
        and state.get("etag") == (expected_etag or "")
        and state.get("last_modified") == (last_modified or "")
        and bool(expected_etag or last_modified)
        and 0 <= recorded_bytes <= offset
        and (expected_size is None or offset <= expected_size)
    )
    if offset and not valid_resume:
        partial.unlink(missing_ok=True)
        state_path.unlink(missing_ok=True)
        offset = 0
    elif offset > recorded_bytes:
        with partial.open("r+b") as partial_stream:
            partial_stream.truncate(recorded_bytes)
            partial_stream.flush()
            os.fsync(partial_stream.fileno())
        offset = recorded_bytes
    elif offset and expected_size is not None and offset == expected_size:
        return offset, redirect_destination, expected_etag, last_modified

    headers: dict[str, str] = {}
    if offset:
        headers["Range"] = f"bytes={offset}-"
        validator = expected_etag or last_modified
        if validator:
            headers["If-Range"] = validator

    try:
        response = _request(url, headers=headers)
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Verified HTTPS download failed for {url}: {exc}") from exc

    with response:
        status = response.status
        response_etag = response.headers.get("ETag")
        response_modified = response.headers.get("Last-Modified")
        parsed_range = None
        if offset:
            content_range = response.headers.get("Content-Range", "")
            parsed_range = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", content_range)
            valid_range = (
                status == 206
                and parsed_range is not None
                and int(parsed_range.group(1)) == offset
                and (not expected_etag or not response_etag or expected_etag == response_etag)
                and (
                    not last_modified or not response_modified or last_modified == response_modified
                )
            )
            if not valid_range:
                partial.unlink(missing_ok=True)
                state_path.unlink(missing_ok=True)
                raise RuntimeError(
                    "Partial response did not match validators; rerun to restart from byte zero"
                )
        else:
            if status != 200:
                raise RuntimeError(f"Unexpected HTTP status {status} for {url}")
            if expected_etag and response_etag and expected_etag != response_etag:
                raise RuntimeError("Object ETag changed between HEAD and GET; retry the download")
            if last_modified and response_modified and last_modified != response_modified:
                raise RuntimeError(
                    "Object Last-Modified changed between HEAD and GET; retry the download"
                )

        state = {
            "url": url,
            "etag": expected_etag or "",
            "last_modified": last_modified or "",
            "bytes_written": str(offset),
        }
        _write_state(state_path, state)
        total = offset
        mode = "ab" if offset else "wb"
        with partial.open(mode) as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                total += len(chunk)
                if total % (8 * 1024 * 1024) < len(chunk):
                    output.flush()
                    os.fsync(output.fileno())
                    state["bytes_written"] = str(total)
                    _write_state(state_path, state)
            output.flush()
            os.fsync(output.fileno())
        state["bytes_written"] = str(total)
        _write_state(state_path, state)

        if expected_size is not None and total != expected_size:
            raise RuntimeError(f"Truncated download: got {total} bytes; expected {expected_size}")
        if (
            status == 206
            and parsed_range
            and parsed_range.group(3).isdecimal()
            and int(parsed_range.group(3)) != total
        ):
            raise RuntimeError(
                f"Resumed download ended at {total} bytes; expected {parsed_range.group(3)}"
            )
        return (
            total,
            redirect_destination,
            expected_etag or response_etag,
            last_modified or response_modified,
        )


def download_file(data_dir: Path, filename: str, source: str) -> DownloadEvidence:
    url, revision = source_url(filename, source)
    data_dir.mkdir(parents=True, exist_ok=True)
    destination = data_dir / filename
    partial = data_dir / f"{filename}.part"
    state_path = data_dir / f"{filename}.part.json"

    if destination.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing file: {destination}; verify it from the existing source manifest"
        )

    upstream_sha, upstream_size = (
        _mirror_file_metadata(filename) if source == "mirror" else (None, None)
    )
    total, redirect_destination, etag, modified = _stream_to_partial(url, partial, state_path)
    digest = _digest_file(partial)
    if upstream_sha and digest != upstream_sha:
        raise RuntimeError(
            f"Downloaded SHA-256 {digest} does not match upstream LFS SHA-256 {upstream_sha}"
        )
    if upstream_size is not None and total != upstream_size:
        raise RuntimeError(f"Downloaded size {total} does not match upstream size {upstream_size}")
    _verify_gzip(partial)
    os.replace(partial, destination)
    state_path.unlink(missing_ok=True)

    return DownloadEvidence(
        filename=filename,
        source=source,
        requested_url=url,
        redirect_destination=redirect_destination,
        revision=revision,
        bytes=total,
        sha256=digest,
        upstream_sha256=upstream_sha,
        upstream_digest_source=f"pinned mirror API LFS oid at revision {revision}"
        if upstream_sha
        else None,
        etag=etag,
        last_modified=modified,
        downloaded_at=datetime.now(UTC).isoformat(),
    )


def download_one(data_dir: Path, filename: str, source: str) -> DownloadEvidence:
    if source != "auto":
        return download_file(data_dir, filename, source)
    try:
        return download_file(data_dir, filename, "publisher")
    except (URLError, OSError) as error:
        return replace(
            download_file(data_dir, filename, "mirror"),
            publisher_fallback_reason=f"{type(error).__name__}: {error}",
        )


def download_dataset(data_dir: Path, source: str) -> list[DownloadEvidence]:
    if source not in {"auto", "publisher", "mirror"}:
        raise ValueError("source must be 'auto', 'publisher', or 'mirror'")
    evidence: list[DownloadEvidence] = []
    for filename in FILES:
        evidence.append(download_one(data_dir, filename, source))
    return evidence
