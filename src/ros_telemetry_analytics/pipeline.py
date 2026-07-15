from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from ros_telemetry_analytics.analysis import analyze_message_index, build_analysis_summary
from ros_telemetry_analytics.config import PipelineConfig, analytics_fingerprint
from ros_telemetry_analytics.discovery import discover_bags, inventory_frame
from ros_telemetry_analytics.models import BagSource, ProcessResult
from ros_telemetry_analytics.reader import scan_bag

LOGGER = logging.getLogger(__name__)
EXPECTED_BAG_ARTIFACTS = {
    "message_index.parquet",
    "relationship_health.parquet",
    "topic_manifest.parquet",
    "topic_health.parquet",
    "vslam_quality.parquet",
    "summary.json",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}-",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(payload, temp_file, indent=2, sort_keys=True)
            temp_file.write("\n")
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}-",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(content)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@contextmanager
def _pipeline_lock(output_root: Path) -> Iterator[None]:
    output_root.mkdir(parents=True, exist_ok=True)
    lock_path = output_root / ".pipeline.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"Another pipeline process holds {lock_path}") from exc
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(f"pid={os.getpid()} started_at={_utc_now()}\n")
        lock_file.flush()
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _existing_summary(target_dir: Path) -> dict[str, Any] | None:
    summary_path = target_dir / "summary.json"
    if not summary_path.exists():
        return None
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _cached_output_complete(target_dir: Path) -> bool:
    if not all((target_dir / name).is_file() for name in EXPECTED_BAG_ARTIFACTS):
        return False
    try:
        for name in EXPECTED_BAG_ARTIFACTS:
            if name.endswith(".parquet"):
                pq.read_schema(target_dir / name)
    except (OSError, ValueError):
        return False
    return True


def _recover_output_root(output_root: Path) -> None:
    staging_root = output_root / ".staging"
    if staging_root.exists():
        shutil.rmtree(staging_root)

    bags_root = output_root / "bags"
    if not bags_root.exists():
        return
    for backup in sorted(bags_root.glob(".*-backup-*")):
        target_name = backup.name[1:].rsplit("-backup-", 1)[0]
        target = bags_root / target_name
        if target.exists():
            shutil.rmtree(backup)
        else:
            os.replace(backup, target)


def _reconcile_bag_outputs(output_root: Path, active_bag_ids: set[str]) -> None:
    bags_root = output_root / "bags"
    if not bags_root.exists():
        return
    for child in bags_root.iterdir():
        if child.name.startswith(".") or child.name in active_bag_ids:
            continue
        if child.is_dir():
            shutil.rmtree(child)


def _publish_stage(stage: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_name(f".{target.name}-backup-{uuid.uuid4().hex[:8]}")
    if target.exists():
        os.replace(target, backup)
    try:
        os.replace(stage, target)
    except Exception:
        if backup.exists():
            os.replace(backup, target)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)


def process_source(
    source: BagSource,
    config: PipelineConfig,
    *,
    force: bool = False,
) -> ProcessResult:
    target_dir = config.output_root / "bags" / source.bag_id
    existing = _existing_summary(target_dir)
    current_analytics_fingerprint = analytics_fingerprint(config.analytics)
    if (
        not force
        and existing
        and _cached_output_complete(target_dir)
        and existing.get("fingerprint") == source.fingerprint
        and existing.get("analytics_fingerprint") == current_analytics_fingerprint
        and existing.get("pipeline_status") == "success"
    ):
        return ProcessResult(
            bag_id=source.bag_id,
            status="skipped",
            source_path=str(source.path),
            fingerprint=source.fingerprint,
            output_path=str(target_dir),
            message_count=int(existing.get("message_count", 0)),
            topic_count=int(existing.get("topic_count", 0)),
            health_status=existing.get("health_status"),
            warning_count=int(existing.get("warning_count", 0)),
        )

    staging_root = config.output_root / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f"{source.bag_id}-", dir=staging_root))
    try:
        scan_summary = scan_bag(source, stage, config.parquet_batch_size)
        topic_health, quality, relationships = analyze_message_index(
            stage / "message_index.parquet",
            stage,
            config.analytics,
        )
        analysis_summary = build_analysis_summary(topic_health, quality, relationships)
        summary = {
            "schema_version": 1,
            "pipeline_status": "success",
            "bag_id": source.bag_id,
            "source_path": str(source.path),
            "source_format": source.format,
            "fingerprint": source.fingerprint,
            "analytics_fingerprint": current_analytics_fingerprint,
            "size_bytes": source.size_bytes,
            "analyzed_at": _utc_now(),
            **scan_summary,
            **analysis_summary,
        }
        _write_json(stage / "summary.json", summary)
        _publish_stage(stage, target_dir)
        return ProcessResult(
            bag_id=source.bag_id,
            status="processed",
            source_path=str(source.path),
            fingerprint=source.fingerprint,
            output_path=str(target_dir),
            message_count=scan_summary["message_count"],
            topic_count=scan_summary["topic_count"],
            health_status=analysis_summary["health_status"],
            warning_count=analysis_summary["warning_count"],
        )
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise


def _render_report(manifest: dict[str, Any]) -> str:
    lines = [
        "# Telemetry Analysis Run",
        "",
        f"Generated: `{manifest['completed_at']}`",
        "",
        f"Discovered: **{manifest['discovered_count']}**  ",
        f"Processed: **{manifest['processed_count']}**  ",
        f"Skipped: **{manifest['skipped_count']}**  ",
        f"Failed: **{manifest['failed_count']}**  ",
        f"Not attempted: **{manifest['not_attempted_count']}**",
        "",
        "| Bag | Pipeline | Health | Messages | Topics | Warnings |",
        "| --- | --- | --- | ---: | ---: | ---: |",
    ]
    for result in manifest["results"]:
        lines.append(
            f"| `{result['bag_id']}` | {result['status']} | "
            f"{result.get('health_status') or '-'} | {result.get('message_count', 0)} | "
            f"{result.get('topic_count', 0)} | {result.get('warning_count', 0)} |"
        )
    return "\n".join(lines) + "\n"


def run_pipeline(
    config: PipelineConfig,
    *,
    force: bool = False,
    fail_fast: bool = False,
) -> dict[str, Any]:
    """Discover and analyze every configured bag with per-source failure isolation."""
    started_at = _utc_now()
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"

    with _pipeline_lock(config.output_root):
        _recover_output_root(config.output_root)
        discovery_errors: list[tuple[Path, OSError]] = []
        sources = discover_bags(
            config.input_roots,
            config.excluded_directory_names,
            on_error=lambda path, exc: discovery_errors.append((path, exc)),
        )
        _reconcile_bag_outputs(config.output_root, {source.bag_id for source in sources})
        inventory = inventory_frame(sources)
        inventory_temp = config.output_root / ".bag_inventory.parquet.tmp"
        inventory.write_parquet(inventory_temp, compression="zstd")
        os.replace(inventory_temp, config.output_root / "bag_inventory.parquet")

        results: list[ProcessResult] = [
            ProcessResult(
                bag_id=(
                    "discovery_error__" + hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:8]
                ),
                status="failed",
                source_path=str(path),
                fingerprint="",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            for path, exc in discovery_errors
        ]
        if fail_fast and discovery_errors:
            results.extend(
                ProcessResult(
                    bag_id=source.bag_id,
                    status="not_attempted",
                    source_path=str(source.path),
                    fingerprint=source.fingerprint,
                )
                for source in sources
            )
            sources_to_process: list[BagSource] = []
        else:
            sources_to_process = sources

        for source_index, source in enumerate(sources_to_process):
            LOGGER.info("Analyzing %s (%s)", source.bag_id, source.path)
            try:
                results.append(process_source(source, config, force=force))
            except Exception as exc:
                LOGGER.exception("Failed to analyze %s", source.bag_id)
                results.append(
                    ProcessResult(
                        bag_id=source.bag_id,
                        status="failed",
                        source_path=str(source.path),
                        fingerprint=source.fingerprint,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                )
                if fail_fast:
                    results.extend(
                        ProcessResult(
                            bag_id=remaining.bag_id,
                            status="not_attempted",
                            source_path=str(remaining.path),
                            fingerprint=remaining.fingerprint,
                        )
                        for remaining in sources_to_process[source_index + 1 :]
                    )
                    break

        result_rows = [result.to_dict() for result in results]
        status_counts = {
            status: sum(row["status"] == status for row in result_rows)
            for status in ("processed", "skipped", "failed", "not_attempted")
        }
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "started_at": started_at,
            "completed_at": _utc_now(),
            "input_roots": [str(path) for path in config.input_roots],
            "output_root": str(config.output_root),
            "discovered_count": len(sources) + len(discovery_errors),
            "processed_count": status_counts["processed"],
            "skipped_count": status_counts["skipped"],
            "failed_count": status_counts["failed"],
            "not_attempted_count": status_counts["not_attempted"],
            "results": result_rows,
        }
        _write_json(config.output_root / "runs" / f"{run_id}.json", manifest)
        _write_json(config.output_root / "latest_run.json", manifest)
        _write_text(config.output_root / "latest_report.md", _render_report(manifest))
        return manifest
