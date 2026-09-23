"""Serialize isolated evidence rebuilds for the local API (macOS/Linux)."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from threading import Lock, Thread

from fastapi import HTTPException

from demo.api.evidence_worker import cleanup_staging
from ros_telemetry_analytics import investigations as evidence

logger = logging.getLogger(__name__)


class EvidencePreparation:
    def __init__(self, root: Path, output: Path):
        self.root = root
        self.output = output
        self.lock = Lock()
        self.active: str | None = None

    def _job(self, dataset_id: str) -> Path:
        return self.output / f".preparation-{dataset_id}.json"

    def _read(self, dataset_id: str) -> dict:
        try:
            return json.loads(self._job(dataset_id).read_text())
        except FileNotFoundError:
            return {"status": "idle"}

    def _claim(self):
        self.output.mkdir(parents=True, exist_ok=True)
        handle = (self.output / ".preparation.lock").open("a")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return None
        return handle

    def status(self, dataset_id: str) -> dict:
        if dataset_id not in evidence.specs(self.root):
            raise HTTPException(404, "Unknown recording")
        with self.lock:
            result = self._read(dataset_id)
            if result["status"] == "running" and self.active != dataset_id:
                handle = self._claim()
                if handle is not None:
                    with handle:
                        # Recheck after acquiring the lock; a worker may just have finished.
                        result = self._read(dataset_id)
                        if result["status"] == "running":
                            result = {
                                "status": "failed",
                                "error": "Rebuild was interrupted. Try again.",
                            }
                            evidence.write_json(self._job(dataset_id), result)
                            cleanup_staging(self.output)
            return result

    def start(self, dataset_id: str) -> dict:
        spec = evidence.specs(self.root).get(dataset_id)
        if spec is None:
            raise HTTPException(404, "Unknown recording")
        if not (self.root / spec["input"]).exists():
            raise HTTPException(409, "Recording source is not installed")
        with self.lock:
            if self.active == dataset_id:
                return self._read(dataset_id)
            handle = self._claim() if self.active is None else None
            if handle is None:
                raise HTTPException(
                    409, "Another recording is rebuilding. Try again when it finishes."
                )
            self.active = dataset_id
            result = {"status": "running", "stage": "Analyzing recording"}
            try:
                evidence.write_json(self._job(dataset_id), result)
                Thread(target=self._run, args=(dataset_id, handle), daemon=True).start()
            except Exception:
                handle.close()
                self.active = None
                evidence.write_json(
                    self._job(dataset_id), {"status": "failed", "error": "Could not start rebuild"}
                )
                raise
            return result

    def _run(self, dataset_id: str, handle) -> None:
        result = {"status": "failed", "error": "Could not rebuild evidence. Try again."}
        try:
            # Match bind-mount ownership on Linux, without changing the API's shared volumes.
            identity = {}
            if os.geteuid() == 0:
                owner = self.output.stat()
                identity = {"user": owner.st_uid, "group": owner.st_gid, "extra_groups": []}
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "demo.api.evidence_worker",
                    "--root",
                    str(self.root),
                    "--output",
                    str(self.output),
                    "--dataset",
                    dataset_id,
                ],
                cwd=Path(__file__).resolve().parents[2],
                stdout=subprocess.PIPE,
                text=True,
                # The child keeps the lock if the API dies, preventing overlapping cleanup.
                pass_fds=(handle.fileno(),),
                check=False,
                **identity,
            )
            if process.stdout.strip():
                result = json.loads(process.stdout.splitlines()[-1])
            if process.returncode != 0 and result.get("status") != "failed":
                result = {
                    "status": "failed",
                    "error": "Evidence worker exited unexpectedly. Try again.",
                }
        except Exception:
            logger.exception("Evidence worker failed for %s", dataset_id)
        finally:
            try:
                cleanup_staging(self.output)
            except OSError:
                logger.exception("Could not remove interrupted rebuild files")
            with self.lock:
                try:
                    evidence.write_json(self._job(dataset_id), result)
                finally:
                    self.active = None
                    handle.close()
