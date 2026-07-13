from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
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
    required = {"org", "team", "resource", "filename", "version", "sha256"}
    for name, specification in assets.items():
        if not isinstance(specification, dict):
            raise ValueError(f"Asset {name!r} must be a mapping")
        missing = required.difference(specification)
        if missing:
            raise ValueError(f"Asset {name!r} is missing required fields: {sorted(missing)}")
        if not SHA256_PATTERN.fullmatch(str(specification["sha256"])):
            raise ValueError(f"Asset {name!r} has an invalid SHA-256 checksum")
    return assets


def _resource_base_url(specification: dict[str, Any]) -> str:
    org = quote(str(specification["org"]), safe="")
    team = quote(str(specification["team"]), safe="")
    resource = quote(str(specification["resource"]), safe="")
    return f"{NGC_RESOURCE_BASE_URL}/{org}/{team}/{resource}"


def _version_values(payload: object) -> list[str]:
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        candidates = []
        for key in ("versions", "resourceVersions", "modelVersions", "recipeVersions", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates.extend(value)
    else:
        candidates = []

    versions: list[str] = []
    for item in candidates:
        if isinstance(item, str):
            versions.append(item)
        elif isinstance(item, dict):
            value = next(
                (item.get(key) for key in ("version", "versionId", "name", "id") if item.get(key)),
                None,
            )
            if value is not None:
                versions.append(str(value))
    return versions


def _candidate_urls(
    session: requests.Session,
    specification: dict[str, Any],
) -> list[str]:
    base_url = _resource_base_url(specification)
    filename = quote(str(specification["filename"]), safe="/")
    configured_version = specification.get("version")
    if configured_version:
        return [f"{base_url}/versions/{quote(str(configured_version), safe='')}/files/{filename}"]

    versions: list[str] = []
    try:
        response = session.get(f"{base_url}/versions", timeout=30)
        response.raise_for_status()
        versions.extend(_version_values(response.json()))
    except (requests.RequestException, ValueError):
        pass
    versions.append("latest")

    urls: list[str] = []
    for version in versions:
        url = f"{base_url}/versions/{quote(version, safe='')}/files/{filename}"
        if url not in urls:
            urls.append(url)
    urls.append(f"{base_url}/files/{filename}")
    return urls


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


def download_file(
    session: requests.Session,
    urls: list[str],
    destination: Path,
    expected_sha256: str | None = None,
) -> str:
    """Download atomically and return the verified SHA-256 digest."""
    if destination.exists():
        return _verify_checksum(destination, expected_sha256)

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial_path = destination.with_suffix(destination.suffix + ".part")
    errors: list[str] = []
    for url in urls:
        try:
            with session.get(url, stream=True, timeout=(30, 120)) as response:
                response.raise_for_status()
                with partial_path.open("wb") as output_file:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            output_file.write(chunk)
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


def extract_archive(
    archive_path: Path,
    destination: Path,
    archive_sha256: str,
) -> None:
    """Extract through a staging directory and publish only a complete tree."""
    completion_marker = destination / ".extraction-complete.json"
    if completion_marker.exists():
        try:
            payload = json.loads(completion_marker.read_text(encoding="utf-8"))
            if payload.get("archive_sha256") == archive_sha256:
                return
        except (OSError, ValueError):
            pass

    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        with tarfile.open(archive_path, "r:gz") as tar_file:
            safe_extract(tar_file, stage)
        (stage / ".extraction-complete.json").write_text(
            json.dumps({"archive_sha256": archive_sha256}, indent=2) + "\n",
            encoding="utf-8",
        )
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(stage, destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def download_asset(asset_name: str, specification: dict[str, Any]) -> Path:
    filename = Path(str(specification["filename"])).name
    archive_path = DOWNLOAD_DIR / asset_name / filename
    extraction_path = EXTRACT_DIR / asset_name
    expected_sha256 = specification.get("sha256")

    with requests.Session() as session:
        session.headers["User-Agent"] = "isaac-robot-telemetry-analytics/0.1.0"
        if archive_path.exists():
            digest = _verify_checksum(archive_path, expected_sha256)
        else:
            digest = download_file(
                session,
                _candidate_urls(session, specification),
                archive_path,
                expected_sha256,
            )
    extract_archive(archive_path, extraction_path, digest)
    return extraction_path
