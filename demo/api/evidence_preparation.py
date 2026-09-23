"""One background evidence rebuild at a time for the local, single-worker API."""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock, Thread

from fastapi import HTTPException

from ros_telemetry_analytics import investigations as evidence
from scripts.curate_investigations import publish

logger = logging.getLogger(__name__)


class EvidencePreparation:
    def __init__(self, root: Path, output: Path):
        self.root = root
        self.output = output
        self.lock = Lock()
        self.jobs: dict[str, dict] = {}
        self.active: str | None = None

    def status(self, dataset_id: str) -> dict:
        if dataset_id not in evidence.specs(self.root):
            raise HTTPException(404, "Unknown recording")
        with self.lock:
            return dict(self.jobs.get(dataset_id, {"status": "idle"}))

    def start(self, dataset_id: str) -> dict:
        spec = evidence.specs(self.root).get(dataset_id)
        if spec is None:
            raise HTTPException(404, "Unknown recording")
        if not (self.root / spec["input"]).exists():
            raise HTTPException(409, "Recording source is not installed")
        with self.lock:
            if self.active == dataset_id:
                return dict(self.jobs[dataset_id])
            if self.active is not None:
                raise HTTPException(
                    409, "Another recording is rebuilding. Try again when it finishes."
                )
            self.active = dataset_id
            self.jobs[dataset_id] = {"status": "running", "stage": "Analyzing recording"}
            try:
                Thread(target=self._run, args=(dataset_id,), daemon=True).start()
            except Exception:
                self.active = None
                self.jobs[dataset_id] = {"status": "failed", "error": "Could not start rebuild"}
                raise
            return dict(self.jobs[dataset_id])

    def _run(self, dataset_id: str) -> None:
        result = {"status": "failed", "error": "Could not rebuild evidence. Try again."}
        try:
            metadata = evidence.build_bundle(self.root, dataset_id, self.output)
            if metadata["status"] not in {"ready", "limited"}:
                raise ValueError("Recording source is not available")
            with self.lock:
                self.jobs[dataset_id] = {"status": "running", "stage": "Attaching reviewed cases"}
            warning = None
            try:
                publish(self.root, self.output, dataset_id, metadata)
            except (OSError, ValueError, KeyError):
                logger.exception("Could not attach reviewed cases for %s", dataset_id)
                warning = "Evidence rebuilt, but reviewed cases could not be attached."
            result = {"status": "completed", "analysis_id": metadata["analysis_id"]}
            if warning:
                result["warning"] = warning
        except PermissionError:
            logger.exception("Evidence output is not writable")
            result["error"] = "Evidence storage is not writable. Restart the updated local app."
        except Exception:
            logger.exception("Evidence rebuild failed for %s", dataset_id)
        finally:
            with self.lock:
                self.jobs[dataset_id] = result
                self.active = None
