from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

import requests
import yaml

from isaac_telemetry.config import PROJECT_ROOT

REPOSITORY_ASSET_CONFIG_PATH = PROJECT_ROOT / "configs" / "asset_sources.yaml"
PACKAGED_ASSET_CONFIG_PATH = Path(__file__).with_name("default_assets.yaml")
ASSET_CONFIG_PATH = (
    REPOSITORY_ASSET_CONFIG_PATH
    if REPOSITORY_ASSET_CONFIG_PATH.exists()
    else PACKAGED_ASSET_CONFIG_PATH
)
DOWNLOAD_DIR = PROJECT_ROOT / "data" / "raw" / "downloads"
EXTRACT_DIR = PROJECT_ROOT / "data" / "raw" / "isaac_ros_assets"
NGC_RESOURCE_BASE_URL = "https://api.ngc.nvidia.com/v2/resources"
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def load_asset_config(config_path: Path = ASSET_CONFIG_PATH) -> dict[str, dict[str, Any]]:
    with config_path.open("r", encoding="utf-8") as config_file:
        payload = yaml.safe_load(config_file) or {}
    assets = payload.get("assets")
    if not isinstance(assets, dict) or not assets:
        raise ValueError(f"No assets configured in {config_path}")
    required = {"org", "team", "resource", "filename", "version", "sha256", "bytes"}
    for name, specification in assets.items():
        if not isinstance(specification, dict):
            raise ValueError(f"Asset {name!r} must be a mapping")
        missing = required.difference(specification)
        if missing:
            raise ValueError(f"Asset {name!r} is missing required fields: {sorted(missing)}")
        if not SHA256_PATTERN.fullmatch(str(specification["sha256"])):
            raise ValueError(f"Asset {name!r} has an invalid SHA-256 checksum")
        if int(specification["bytes"]) < 1:
            raise ValueError(f"Asset {name!r} must have a positive byte size")
    return assets


def _resource_base_url(specification: dict[str, Any]) -> str:
    org = quote(str(specification["org"]), safe="")
    team = quote(str(specification["team"]), safe="")
    resource = quote(str(specification["resource"]), safe="")
    return f"{NGC_RESOURCE_BASE_URL}/{org}/{team}/{resource}"


def _candidate_urls(specification: dict[str, Any]) -> list[str]:
    base_url = _resource_base_url(specification)
    filename = quote(str(specification["filename"]), safe="/")
    version = quote(str(specification["version"]), safe="")
    return [f"{base_url}/versions/{version}/files/{filename}"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_checksum(path: Path, expected_sha256: str | None) -> str:
    actual = sha256_file(path)
    if expected_sha256 and actual.lower() != expected_sha256.lower():
        raise ValueError(
            f"Checksum mismatch for {path}: expected {expected_sha256}, received {actual}"
        )
    return actual


def _verify_size(path: Path, expected_size_bytes: int | None) -> None:
    if expected_size_bytes is not None and path.stat().st_size != expected_size_bytes:
        raise ValueError(
            f"Size mismatch for {path}: expected {expected_size_bytes}, "
            f"received {path.stat().st_size}"
        )


def download_file(
    session: requests.Session,
    urls: list[str],
    destination: Path,
    expected_sha256: str | None = None,
    expected_size_bytes: int | None = None,
) -> str:
    """Download atomically and return the verified SHA-256 digest."""
    if destination.exists():
        _verify_size(destination, expected_size_bytes)
        return _verify_checksum(destination, expected_sha256)

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial_path = destination.with_suffix(destination.suffix + ".part")
    errors: list[str] = []
    for url in urls:
        try:
            with session.get(url, stream=True, timeout=(30, 120)) as response:
                response.raise_for_status()
                content_length = response.headers.get("Content-Length")
                if (
                    expected_size_bytes is not None
                    and content_length is not None
                    and int(content_length) > expected_size_bytes
                ):
                    raise ValueError(
                        f"Download exceeds expected size: {content_length} > {expected_size_bytes}"
                    )
                bytes_written = 0
                with partial_path.open("wb") as output_file:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            bytes_written += len(chunk)
                            if (
                                expected_size_bytes is not None
                                and bytes_written > expected_size_bytes
                            ):
                                raise ValueError(
                                    f"Download exceeds expected size: "
                                    f"{bytes_written} > {expected_size_bytes}"
                                )
                            output_file.write(chunk)
            _verify_size(partial_path, expected_size_bytes)
            digest = _verify_checksum(partial_path, expected_sha256)
            os.replace(partial_path, destination)
            return digest
        except (OSError, ValueError, requests.RequestException) as exc:
            errors.append(f"{url}: {exc}")
            partial_path.unlink(missing_ok=True)
    raise RuntimeError("Asset download failed:\n" + "\n".join(errors))


def safe_extract(tar_file: tarfile.TarFile, destination: Path) -> None:
    """Extract regular files/directories only, rejecting links and special members."""
    destination_root = destination.resolve()
    members = tar_file.getmembers()
    for member in members:
        member_path = PurePosixPath(member.name)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise RuntimeError(f"Unsafe archive path: {member.name}")
        if not (member.isfile() or member.isdir()):
            raise RuntimeError(f"Unsupported archive member type: {member.name}")
        target_path = (destination / Path(*member_path.parts)).resolve()
        if target_path != destination_root and destination_root not in target_path.parents:
            raise RuntimeError(f"Archive member escapes destination: {member.name}")
    tar_file.extractall(destination, members=members, filter="data")


def _recover_extraction(destination: Path) -> None:
    backups = sorted(destination.parent.glob(f".{destination.name}-backup-*"))
    if destination.exists():
        for backup in backups:
            shutil.rmtree(backup)
        return
    if backups:
        os.replace(backups[-1], destination)
        for backup in backups[:-1]:
            shutil.rmtree(backup)


def _publish_extraction(stage: Path, destination: Path) -> None:
    backup = destination.with_name(f".{destination.name}-backup-{uuid.uuid4().hex[:8]}")
    if destination.exists():
        os.replace(destination, backup)
    try:
        os.replace(stage, destination)
    except Exception:
        if backup.exists():
            os.replace(backup, destination)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)


def extract_archive(
    archive_path: Path,
    destination: Path,
    archive_sha256: str,
) -> None:
    """Extract through a staging directory and publish only a complete tree."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    _recover_extraction(destination)
    completion_marker = destination / ".extraction-complete.json"
    if completion_marker.exists():
        try:
            payload = json.loads(completion_marker.read_text(encoding="utf-8"))
            if payload.get("archive_sha256") == archive_sha256:
                return
        except (OSError, ValueError):
            pass

    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        with tarfile.open(archive_path, "r:gz") as tar_file:
            safe_extract(tar_file, stage)
        (stage / ".extraction-complete.json").write_text(
            json.dumps({"archive_sha256": archive_sha256}, indent=2) + "\n",
            encoding="utf-8",
        )
        _publish_extraction(stage, destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


@contextmanager
def _asset_lock(asset_name: str) -> Iterator[None]:
    if Path(asset_name).name != asset_name:
        raise ValueError(f"Unsafe asset name: {asset_name}")
    lock_path = DOWNLOAD_DIR / asset_name / ".download.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def download_asset(asset_name: str, specification: dict[str, Any]) -> Path:
    filename = Path(str(specification["filename"])).name
    archive_path = DOWNLOAD_DIR / asset_name / filename
    extraction_path = EXTRACT_DIR / asset_name
    expected_sha256 = str(specification["sha256"])
    expected_size_bytes = int(specification["bytes"])

    with _asset_lock(asset_name), requests.Session() as session:
        session.headers["User-Agent"] = "isaac-robot-telemetry-analytics/0.1.0"
        digest = download_file(
            session,
            _candidate_urls(specification),
            archive_path,
            expected_sha256,
            expected_size_bytes,
        )
        extract_archive(archive_path, extraction_path, digest)
    return extraction_path
