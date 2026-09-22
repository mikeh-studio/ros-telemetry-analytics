"""Read-only access to prepared recording evidence; no replay or bag parsing on request."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ros_telemetry_analytics import investigations as evidence


def router(root: Path, output: Path) -> APIRouter:
    routes = APIRouter(prefix="/api/investigations", tags=["recorded evidence"])

    def load(dataset_id: str, analysis_id: str | None = None):
        try:
            return evidence.load_bundle(root, output, dataset_id, analysis_id)
        except KeyError as exc:
            raise HTTPException(404, "Unknown recording or incomplete evidence") from exc
        except FileNotFoundError as exc:
            raise HTTPException(
                404, "Recording evidence is not prepared or source is missing"
            ) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @lru_cache(maxsize=16)
    def cached_interval(
        directory: str, metadata_json: str, start: float, end: float, topic: str | None
    ):
        return evidence.interval(Path(directory), json.loads(metadata_json), start, end, topic)

    @routes.get("")
    def collection():
        return evidence.collection(root, output)

    @routes.get("/{dataset_id}")
    def detail(dataset_id: str):
        directory, metadata = load(dataset_id)
        payload = evidence.public_metadata(directory, metadata)
        payload["continuity_checks"] = evidence.rows(
            directory / metadata["analysis_path"] / "vslam_quality.parquet"
        )[:200]
        return evidence.clean(payload)

    @routes.get("/{dataset_id}/interval")
    def interval(
        dataset_id: str,
        analysis_id: str = Query(min_length=32, max_length=32),
        start_s: float = Query(ge=0, allow_inf_nan=False),
        end_s: float = Query(gt=0, allow_inf_nan=False),
        topic: str | None = Query(default=None, max_length=512),
    ):
        directory, metadata = load(dataset_id, analysis_id)
        try:
            return cached_interval(
                str(directory), json.dumps(metadata, sort_keys=True), start_s, end_s, topic
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    return routes
