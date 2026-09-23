from threading import Event

import pytest
from fastapi import HTTPException

from demo.api import evidence_preparation as jobs


def test_rebuild_deduplicates_reports_completion_and_preserves_annotations(tmp_path, monkeypatch):
    started, release, published = Event(), Event(), Event()
    source = tmp_path / "source.bag"
    source.touch()
    monkeypatch.setattr(
        jobs.evidence,
        "specs",
        lambda root: {
            "a": {"input": "source.bag"},
            "b": {"input": "source.bag"},
            "missing": {"input": "missing.bag"},
        },
    )

    def build(root, dataset_id, output):
        started.set()
        assert release.wait(5)
        return {"status": "ready", "analysis_id": "new-analysis"}

    monkeypatch.setattr(jobs.evidence, "build_bundle", build)
    monkeypatch.setattr(jobs, "publish", lambda *args: published.set())
    manager = jobs.EvidencePreparation(tmp_path, tmp_path / "output")
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
        with pytest.raises(HTTPException) as busy:
            manager.start("b")
        assert busy.value.status_code == 409
    finally:
        release.set()
    assert published.wait(5)
    # Take the lock after the worker's final publication without assuming scheduling.
    for _ in range(1000):
        if manager.status("a")["status"] == "completed":
            break
        Event().wait(0.001)
    assert manager.status("a") == {"status": "completed", "analysis_id": "new-analysis"}


def test_failed_rebuild_releases_slot_and_annotation_failure_is_nonfatal(tmp_path, monkeypatch):
    manager = jobs.EvidencePreparation(tmp_path, tmp_path / "output")
    monkeypatch.setattr(jobs.evidence, "specs", lambda root: {"a": {}})

    def fail(*args):
        raise PermissionError("read-only mount")

    monkeypatch.setattr(jobs.evidence, "build_bundle", fail)
    manager.active = "a"
    manager._run("a")
    assert manager.status("a")["status"] == "failed"
    assert "not writable" in manager.status("a")["error"]
    assert manager.active is None
    monkeypatch.setattr(
        jobs.evidence,
        "build_bundle",
        lambda *args: {
            "status": "limited",
            "analysis_id": "new",
        },
    )
    monkeypatch.setattr(jobs, "publish", fail)
    manager._run("a")
    assert manager.status("a")["status"] == "completed"
    assert "reviewed cases" in manager.status("a")["warning"]
