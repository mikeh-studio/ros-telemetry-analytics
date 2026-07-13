from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

import polars as pl
import yaml

from isaac_telemetry.models import BagSource

BAG_SUFFIXES = {".bag": "rosbag1", ".db3": "rosbag2_sqlite3", ".mcap": "rosbag2_mcap"}
INVENTORY_SCHEMA = {
    "bag_id": pl.Utf8,
    "path": pl.Utf8,
    "format": pl.Utf8,
    "container": pl.Utf8,
    "size_bytes": pl.Int64,
    "fingerprint": pl.Utf8,
}


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return slug or "bag"


def _directory_format(path: Path) -> str:
    metadata_path = path / "metadata.yaml"
    try:
        payload = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
        storage = payload.get("rosbag2_bagfile_information", {}).get("storage_identifier")
    except (OSError, yaml.YAMLError):
        storage = None
    if storage == "mcap":
        return "rosbag2_mcap"
    if storage == "sqlite3":
        return "rosbag2_sqlite3"
    return "rosbag2"


def _source_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    files = [path / "metadata.yaml"]
    files.extend(
        child
        for child in path.rglob("*")
        if child.is_file() and child.suffix.lower() in BAG_SUFFIXES
    )
    return sorted({child.resolve() for child in files if child.exists()})


def _fingerprint(path: Path) -> tuple[str, int]:
    records: list[dict[str, int | str]] = []
    total_size = 0
    for file_path in _source_files(path):
        stat = file_path.stat()
        total_size += stat.st_size
        records.append(
            {
                "name": file_path.name if path.is_file() else str(file_path.relative_to(path)),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), total_size


def _candidate_paths(root: Path, excluded_names: frozenset[str]) -> list[tuple[Path, Path]]:
    if not root.exists():
        raise FileNotFoundError(f"Input path does not exist: {root}")
    if root.is_file():
        if root.suffix.lower() not in BAG_SUFFIXES:
            raise ValueError(f"Unsupported input file: {root}")
        return [(root.resolve(), root.parent.resolve())]
    if (root / "metadata.yaml").exists():
        return [(root.resolve(), root.parent.resolve())]

    candidates: list[tuple[Path, Path]] = []
    for current, directory_names, file_names in os.walk(root):
        current_path = Path(current)
        directory_names[:] = sorted(name for name in directory_names if name not in excluded_names)

        if "metadata.yaml" in file_names:
            candidates.append((current_path.resolve(), root.resolve()))
            directory_names[:] = []
            continue

        for file_name in sorted(file_names):
            file_path = current_path / file_name
            if file_path.suffix.lower() in BAG_SUFFIXES:
                candidates.append((file_path.resolve(), root.resolve()))
    return candidates


def discover_bags(
    roots: tuple[Path, ...] | list[Path],
    excluded_directory_names: frozenset[str] = frozenset({"downloads"}),
) -> list[BagSource]:
    """Discover one canonical source per bag across all configured roots."""
    candidates: dict[Path, Path] = {}
    for root in roots:
        for source_path, discovery_root in _candidate_paths(
            root.expanduser().resolve(),
            excluded_directory_names,
        ):
            candidates.setdefault(source_path, discovery_root)

    base_ids: list[str] = []
    ordered = sorted(candidates.items(), key=lambda item: str(item[0]))
    for source_path, discovery_root in ordered:
        relative = source_path.relative_to(discovery_root)
        relative_text = str(relative.with_suffix("")) if source_path.is_file() else str(relative)
        base_ids.append(_slug(relative_text.replace(os.sep, "__")))

    id_counts = Counter(base_ids)
    used_ids: set[str] = set()
    sources: list[BagSource] = []
    for (source_path, _discovery_root), base_id in zip(ordered, base_ids, strict=True):
        bag_id = base_id
        if id_counts[base_id] > 1 or bag_id in used_ids:
            suffix = hashlib.sha256(str(source_path).encode("utf-8")).hexdigest()[:8]
            bag_id = f"{base_id}__{suffix}"
        used_ids.add(bag_id)

        fingerprint, size_bytes = _fingerprint(source_path)
        file_format = (
            _directory_format(source_path)
            if source_path.is_dir()
            else BAG_SUFFIXES[source_path.suffix.lower()]
        )
        sources.append(
            BagSource(
                bag_id=bag_id,
                path=source_path,
                format=file_format,
                container="directory" if source_path.is_dir() else "file",
                size_bytes=size_bytes,
                fingerprint=fingerprint,
            )
        )
    return sources


def inventory_frame(sources: list[BagSource]) -> pl.DataFrame:
    rows = [source.to_dict() for source in sources]
    return (
        pl.DataFrame(rows, schema=INVENTORY_SCHEMA)
        if rows
        else pl.DataFrame(schema=INVENTORY_SCHEMA)
    )
