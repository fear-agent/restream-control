from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.request import Request, urlopen

MAX_UPDATE_BYTES = 600 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 20_000


def select_release_assets(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    tag = str(payload.get("tag_name", "")).strip()
    release_url = str(payload.get("html_url", "")).strip()
    zip_name = ""
    zip_url = ""
    checksum_url = ""
    assets = payload.get("assets", [])
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name", "")).strip()
            url = str(asset.get("browser_download_url", "")).strip()
            lower_name = name.lower()
            if lower_name.startswith("restreamcontrol-") and lower_name.endswith(".zip"):
                zip_name, zip_url = name, url
                break
        if zip_name:
            expected_names = {f"{zip_name}.sha256".lower(), f"{Path(zip_name).stem}.sha256".lower()}
            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                if str(asset.get("name", "")).strip().lower() in expected_names:
                    checksum_url = str(asset.get("browser_download_url", "")).strip()
                    break
    if not tag or not release_url:
        raise RuntimeError("GitHub did not return a release tag.")
    return tag, release_url, zip_url, checksum_url


def parse_sha256(text: str) -> str:
    match = re.search(r"(?i)(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", text)
    if not match:
        raise RuntimeError("The release checksum file does not contain a valid SHA-256 value.")
    return match.group(0).lower()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(url: str, destination: Path, progress: Callable[[int], None] | None = None) -> None:
    if not url.lower().startswith("https://"):
        raise RuntimeError("Updates must be downloaded over HTTPS.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "Restream-Control"})
    written = 0
    with urlopen(request, timeout=30) as response, destination.open("wb") as output:
        content_length = int(response.headers.get("Content-Length", "0") or 0)
        if content_length > MAX_UPDATE_BYTES:
            raise RuntimeError("The update package is unexpectedly large.")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_UPDATE_BYTES:
                raise RuntimeError("The update package exceeded the size limit.")
            output.write(chunk)
            if progress:
                progress(written)


def _safe_member_path(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
        raise RuntimeError(f"Unsafe path in update archive: {name}")
    return path


def extract_verified_package(zip_path: Path, checksum_text: str, staging_dir: Path) -> Path:
    expected = parse_sha256(checksum_text)
    actual = file_sha256(zip_path)
    if actual != expected:
        raise RuntimeError("The downloaded ZIP failed SHA-256 verification. It was not installed.")
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)
    total_size = 0
    with zipfile.ZipFile(zip_path) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ARCHIVE_ENTRIES:
            raise RuntimeError("The update archive contains too many files.")
        for entry in entries:
            path = _safe_member_path(entry.filename)
            total_size += max(0, entry.file_size)
            if total_size > MAX_UPDATE_BYTES:
                raise RuntimeError("The expanded update package is unexpectedly large.")
            mode = (entry.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise RuntimeError("Symbolic links are not allowed in update packages.")
            destination = (staging_dir / Path(*path.parts)).resolve()
            try:
                destination.relative_to(staging_dir.resolve())
            except ValueError as exc:
                raise RuntimeError(f"Unsafe path in update archive: {entry.filename}") from exc
        archive.extractall(staging_dir)
    candidates = list(staging_dir.rglob("Restream Control.exe"))
    if len(candidates) != 1:
        raise RuntimeError("The update package must contain exactly one Restream Control.exe.")
    package_root = candidates[0].parent
    if not (package_root / "apply_update.ps1").is_file():
        raise RuntimeError("The update package is missing its update helper.")
    return package_root


def new_transaction_dir(updates_dir: Path, tag: str) -> Path:
    safe_tag = re.sub(r"[^A-Za-z0-9._-]+", "-", tag).strip("-") or "update"
    path = Path(updates_dir) / "downloads" / f"{safe_tag}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def latest_backup(backup_dir: Path) -> Path | None:
    candidates = [path for path in Path(backup_dir).glob("*") if path.is_dir() and (path / "Restream Control.exe").is_file()]
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def launch_helper(helper: Path, arguments: list[str]) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper), *arguments],
        cwd=str(helper.parent),
        creationflags=flags,
        close_fds=True,
    )


def write_health_marker(path: Path, token: str, version: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps({"token": token, "version": version, "pid": os.getpid()}), encoding="utf-8")
    temp.replace(path)
