from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from ros_telemetry_analytics.discovery import BAG_SUFFIXES, discover_bags

DEFAULT_DATASET_ID = "warehouse_run_17"
PUBLIC_DATASET_MANIFEST = Path("configs/public_test_datasets.yaml")
SUPPORTED_UPLOAD_SUFFIXES = frozenset(BAG_SUFFIXES)

DISPLAY_NAMES = {
    "tum_rgbd_freiburg1_xyz": "TUM RGB-D · Freiburg 1 XYZ",
    "tum_vi_room4_512": "TUM VI · Room 4 512",
    "lilocbench_dynamics_0": "LILocBench · Dynamics 0",
    "openloris_scene_cafe1_1_2": "OpenLORIS Scene · Cafe 1-1",
    "arco_ros2_trajectory_1": "ARCO ROS 2 · Trajectory 1",
}


@dataclass(frozen=True)
class ReplayDataset:
    dataset_id: str
    name: str
    description: str
    source: str
    file_format: str
    path: Path | None
    status: str
    size_bytes: int | None = None
    mission_duration_ms: int | None = None
    topic_count: int | None = None
    uploaded: bool = False
    supports_camera_dropout: bool = False

    @property
    def selectable(self) -> bool:
        return self.status == "ready" and self.path is not None

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("path")
        payload["selectable"] = self.selectable
        return payload


def safe_upload_name(filename: str) -> str:
    name = Path(filename).name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem).strip("._-") or "recording"
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_UPLOAD_SUFFIXES))
        raise ValueError(f"Upload a supported ROS recording ({supported})")
    return f"{stem}{suffix}"


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _manifest_catalog(root: Path, manifest_path: Path) -> list[ReplayDataset]:
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []

    results: list[ReplayDataset] = []
    for dataset_id, metadata in manifest.get("datasets", {}).items():
        if not (
            metadata.get("public_robotics_suite")
            or dataset_id in {"tum_rgbd_freiburg1_xyz", "tum_vi_room4_512"}
        ):
            continue

        configured_path = metadata.get("local_path") or metadata.get("local_artifact")
        path = _resolve(root, configured_path) if configured_path else None
        status = "not_installed"
        size_bytes: int | None = None
        file_format = str(metadata.get("format", "rosbag"))
        if path is not None and path.is_file():
            size_bytes = path.stat().st_size
            expected_size = metadata.get("bytes")
            if path.suffix.lower() not in SUPPORTED_UPLOAD_SUFFIXES:
                status = "needs_extraction"
            elif expected_size is not None and size_bytes != int(expected_size):
                status = "invalid"
            else:
                status = "ready"

        notes = metadata.get("notes") or []
        description = str(notes[0]) if notes else str(metadata.get("workflow", "Public ROS data"))
        results.append(
            ReplayDataset(
                dataset_id=str(dataset_id),
                name=DISPLAY_NAMES.get(str(dataset_id), str(dataset_id).replace("_", " ").title()),
                description=description,
                source="public_dataset",
                file_format=file_format,
                path=path if status == "ready" else None,
                status=status,
                size_bytes=size_bytes or metadata.get("bytes"),
            )
        )
    return results


def _uploaded_catalog(upload_dir: Path) -> list[ReplayDataset]:
    if not upload_dir.is_dir():
        return []
    results: list[ReplayDataset] = []
    for path in sorted(upload_dir.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_UPLOAD_SUFFIXES:
            continue
        try:
            sources = discover_bags([path])
        except (OSError, ValueError):
            sources = []
        status = "ready" if len(sources) == 1 and path.stat().st_size > 0 else "invalid"
        results.append(
            ReplayDataset(
                dataset_id=f"upload:{path.name}",
                name=path.stem.replace("_", " ").replace("-", " ").strip().title(),
                description="User-uploaded ROS recording stored in the local Docker volume.",
                source="user_upload",
                file_format=BAG_SUFFIXES[path.suffix.lower()],
                path=path if status == "ready" else None,
                status=status,
                size_bytes=path.stat().st_size,
                uploaded=True,
            )
        )
    return results


def dataset_catalog(
    *,
    root: Path,
    fixture_path: Path,
    upload_dir: Path,
    manifest_path: Path | None = None,
) -> list[ReplayDataset]:
    manifest_path = manifest_path or root / PUBLIC_DATASET_MANIFEST
    built_in = ReplayDataset(
        dataset_id=DEFAULT_DATASET_ID,
        name="Warehouse Run 17",
        description="Deterministic 90-second ROS 2 mission with optional camera dropout.",
        source="built_in",
        file_format="rosbag2_mcap",
        path=fixture_path if fixture_path.is_file() else None,
        status="ready" if fixture_path.is_file() else "not_installed",
        size_bytes=fixture_path.stat().st_size if fixture_path.is_file() else None,
        mission_duration_ms=90_000,
        topic_count=4,
        supports_camera_dropout=True,
    )
    return [
        built_in,
        *_manifest_catalog(root, manifest_path),
        *_uploaded_catalog(upload_dir),
    ]


def resolve_dataset(
    dataset_id: str,
    *,
    root: Path,
    fixture_path: Path,
    upload_dir: Path,
    manifest_path: Path | None = None,
) -> ReplayDataset:
    datasets = dataset_catalog(
        root=root,
        fixture_path=fixture_path,
        upload_dir=upload_dir,
        manifest_path=manifest_path,
    )
    dataset = next((item for item in datasets if item.dataset_id == dataset_id), None)
    if dataset is None:
        raise ValueError(f"Unknown dataset: {dataset_id}")
    if not dataset.selectable:
        raise ValueError(f"Dataset {dataset.name} is not ready ({dataset.status})")
    return dataset
