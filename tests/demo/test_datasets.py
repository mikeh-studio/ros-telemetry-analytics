from pathlib import Path

import pytest

from demo.common.datasets import (
    dataset_catalog,
    resolve_dataset,
    safe_upload_name,
)


def test_catalog_exposes_ready_and_unavailable_public_datasets(tmp_path: Path) -> None:
    fixture = tmp_path / "warehouse.mcap"
    fixture.write_bytes(b"fixture")
    public_bag = tmp_path / "public" / "dynamics_0.bag"
    public_bag.parent.mkdir()
    public_bag.write_bytes(b"public")
    manifest = tmp_path / "datasets.yaml"
    manifest.write_text(
        f"""
datasets:
  lilocbench_dynamics_0:
    public_robotics_suite: true
    local_artifact: {public_bag}
    format: rosbag1
    bytes: 6
    notes: [Small dynamic mission.]
  openloris_scene_cafe1_1_2:
    public_robotics_suite: true
    local_artifact: {tmp_path / "missing.tar"}
    format: rosbag1_in_tar
    notes: [Large opt-in archive.]
""",
        encoding="utf-8",
    )

    catalog = dataset_catalog(
        root=tmp_path,
        fixture_path=fixture,
        upload_dir=tmp_path / "uploads",
        manifest_path=manifest,
    )

    by_id = {dataset.dataset_id: dataset for dataset in catalog}
    assert by_id["warehouse_run_17"].selectable is True
    assert by_id["lilocbench_dynamics_0"].status == "ready"
    assert by_id["openloris_scene_cafe1_1_2"].status == "not_installed"
    assert by_id["openloris_scene_cafe1_1_2"].selectable is False


def test_resolve_dataset_rejects_unavailable_and_unknown_entries(tmp_path: Path) -> None:
    fixture = tmp_path / "warehouse.mcap"
    fixture.write_bytes(b"fixture")
    manifest = tmp_path / "datasets.yaml"
    manifest.write_text(
        """
datasets:
  arco_ros2_trajectory_1:
    public_robotics_suite: true
    local_artifact: missing.zip
    format: rosbag2_sqlite3_in_zip
""",
        encoding="utf-8",
    )
    kwargs = {
        "root": tmp_path,
        "fixture_path": fixture,
        "upload_dir": tmp_path / "uploads",
        "manifest_path": manifest,
    }

    with pytest.raises(ValueError, match="not ready"):
        resolve_dataset("arco_ros2_trajectory_1", **kwargs)
    with pytest.raises(ValueError, match="Unknown dataset"):
        resolve_dataset("path-traversal", **kwargs)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("mission run.mcap", "mission_run.mcap"),
        ("../robot.bag", "robot.bag"),
        ("telemetry.DB3", "telemetry.db3"),
    ],
)
def test_safe_upload_name(filename: str, expected: str) -> None:
    assert safe_upload_name(filename) == expected


def test_safe_upload_name_rejects_archives() -> None:
    with pytest.raises(ValueError, match="supported ROS recording"):
        safe_upload_name("recording.zip")
