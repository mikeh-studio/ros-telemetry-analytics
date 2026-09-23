import json
import os
import subprocess
import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from demo.api import evidence_preparation as jobs
from demo.api import evidence_worker as worker


def wait_for_job(manager, dataset_id):
    for _ in range(1000):
        result = manager.status(dataset_id)
        if result["status"] != "running":
            return result
        Event().wait(0.005)
    pytest.fail("Worker did not finish")


def test_rebuild_runs_in_child_and_serializes_across_managers(tmp_path, monkeypatch):
    started, release = Event(), Event()
    (tmp_path / "source.bag").touch()
    monkeypatch.setattr(
        jobs.evidence,
        "specs",
        lambda root: {
            "a": {"input": "source.bag"},
            "b": {"input": "source.bag"},
            "missing": {"input": "missing.bag"},
        },
    )

    def run(command, **kwargs):
        assert command[:3] == [sys.executable, "-m", "demo.api.evidence_worker"]
        assert command[-2:] == ["--dataset", "a"]
        assert kwargs["pass_fds"]
        if os.geteuid() == 0:
            assert kwargs["user"] == tmp_path.stat().st_uid
        started.set()
        assert release.wait(5)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "completed",
                    "analysis_id": "new-analysis",
                }
            ),
        )

    monkeypatch.setattr(jobs.subprocess, "run", run)
    manager = jobs.EvidencePreparation(tmp_path, tmp_path / "output")
    other = jobs.EvidencePreparation(tmp_path, tmp_path / "output")
    assert manager.status("a") == {"status": "idle"}
    with pytest.raises(HTTPException) as unknown:
        manager.start("unknown")
    assert unknown.value.status_code == 404
    with pytest.raises(HTTPException) as missing:
        manager.start("missing")
    assert missing.value.status_code == 409
    try:
        assert manager.start("a")["status"] == "running"
        assert started.wait(5)
        assert manager.start("a")["status"] == "running"
        assert other.status("a")["status"] == "running"
        with pytest.raises(HTTPException) as busy:
            other.start("b")
        assert busy.value.status_code == 409
    finally:
        release.set()
    assert wait_for_job(manager, "a") == {"status": "completed", "analysis_id": "new-analysis"}
    assert other.status("a") == manager.status("a")


def test_worker_death_cleans_partial_data_and_releases_slot(tmp_path, monkeypatch):
    (tmp_path / "source.bag").touch()
    output = tmp_path / "output"
    orphan = output / "a" / ".rebuild-interrupted"
    orphan.mkdir(parents=True)
    (orphan / "partial").touch()
    monkeypatch.setattr(jobs.evidence, "specs", lambda root: {"a": {"input": "source.bag"}})
    monkeypatch.setattr(
        jobs.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=-9, stdout="")
    )
    manager = jobs.EvidencePreparation(tmp_path, output)
    manager.start("a")
    assert wait_for_job(manager, "a")["status"] == "failed"
    assert not orphan.exists()
    assert manager.active is None
    manager.start("a")
    assert wait_for_job(manager, "a")["status"] == "failed"


def test_interrupted_job_is_detected_after_api_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs.evidence, "specs", lambda root: {"a": {}})
    output = tmp_path / "output"
    jobs.evidence.write_json(output / ".preparation-a.json", {"status": "running"})
    orphan = output / "a" / ".rebuild-orphan"
    orphan.mkdir(parents=True)
    result = jobs.EvidencePreparation(tmp_path, output).status("a")
    assert result["status"] == "failed"
    assert "interrupted" in result["error"]
    assert not orphan.exists()


def fake_builder(root, dataset_id, output):
    metadata = {"status": "ready", "analysis_id": "a" * 32}
    worker.evidence.write_json(
        output / dataset_id / metadata["analysis_id"] / "metadata.json", metadata
    )
    return metadata


def test_worker_publishes_annotations_then_retains_two_versions(tmp_path, monkeypatch):
    output = tmp_path / "output"
    directory = output / "a"
    for index in range(3):
        old = directory / (str(index) * 32)
        worker.evidence.write_json(old / "metadata.json", {})
        os.utime(old, ns=(index + 1, index + 1))
    (directory / "user-notes").mkdir()
    worker.evidence.write_json(directory / "latest.json", {"analysis_id": "2" * 32})
    monkeypatch.setattr(worker.evidence, "build_bundle", fake_builder)

    def annotate(root, staging, dataset, metadata):
        assert json.loads((directory / "latest.json").read_text())["analysis_id"] == "2" * 32
        worker.evidence.write_json(
            staging / dataset / metadata["analysis_id"] / "annotations.json", {}
        )

    monkeypatch.setattr(worker, "publish", annotate)
    assert worker.rebuild(tmp_path, output, "a")["status"] == "completed"
    assert (directory / ("a" * 32) / "annotations.json").exists()
    assert (directory / ("2" * 32)).exists()
    assert not (directory / ("1" * 32)).exists()
    assert not (directory / ("0" * 32)).exists()
    assert (directory / "user-notes").exists()
    assert not list(directory.glob(".rebuild-*"))


def test_failed_build_preserves_published_version_and_removes_staging(tmp_path, monkeypatch):
    output = tmp_path / "output"
    pointer = output / "a" / "latest.json"
    worker.evidence.write_json(pointer, {"analysis_id": "old"})

    def fail(root, dataset, staging):
        (staging / "partial").touch()
        raise ValueError("Invalid provenance")

    monkeypatch.setattr(worker.evidence, "build_bundle", fail)
    with pytest.raises(ValueError, match="provenance"):
        worker.rebuild(tmp_path, output, "a")
    assert json.loads(pointer.read_text()) == {"analysis_id": "old"}
    assert not list((output / "a").glob(".rebuild-*"))


def test_failed_publication_removes_unpublished_version(tmp_path, monkeypatch):
    output = tmp_path / "output"
    monkeypatch.setattr(worker.evidence, "build_bundle", fake_builder)
    monkeypatch.setattr(worker, "publish", lambda *args: None)
    original = worker.evidence.write_json

    def fail_pointer(path, value):
        if path == output / "a" / "latest.json":
            raise PermissionError("read-only")
        original(path, value)

    monkeypatch.setattr(worker.evidence, "write_json", fail_pointer)
    with pytest.raises(PermissionError):
        worker.rebuild(tmp_path, output, "a")
    assert not (output / "a" / ("a" * 32)).exists()
    assert not list((output / "a").glob(".rebuild-*"))


def test_annotation_failure_is_nonfatal(tmp_path, monkeypatch):
    monkeypatch.setattr(worker.evidence, "build_bundle", fake_builder)

    def fail(*args):
        raise ValueError("Annotation mismatch")

    monkeypatch.setattr(worker, "publish", fail)
    result = worker.rebuild(tmp_path, tmp_path / "output", "a")
    assert result["status"] == "completed"
    assert "reviewed cases" in result["warning"]


def test_actual_worker_process_reports_failure(tmp_path):
    # Exercise the real Python entry point, exit code and machine-readable result.
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "demo.api.evidence_worker",
            "--root",
            str(tmp_path),
            "--output",
            str(tmp_path / "output"),
            "--dataset",
            "missing",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 1
    assert json.loads(process.stdout)["status"] == "failed"


def test_root_api_drops_worker_to_output_owner(tmp_path, monkeypatch):
    output = tmp_path / "output"
    manager = jobs.EvidencePreparation(tmp_path, output)
    handle = manager._claim()
    monkeypatch.setattr(jobs.os, "geteuid", lambda: 0)
    captured = {}

    def run(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout='{"status": "completed"}')

    monkeypatch.setattr(jobs.subprocess, "run", run)
    manager._run("a", handle)
    assert captured["user"] == output.stat().st_uid
    assert captured["group"] == output.stat().st_gid
    assert captured["extra_groups"] == []
