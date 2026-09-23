"""Isolated rebuild worker; invoked by the API with an inherited rebuild lock."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from ros_telemetry_analytics import investigations as evidence
from scripts.curate_investigations import publish

logger = logging.getLogger(__name__)


def cleanup_staging(output: Path) -> None:
    # Only called while holding the global rebuild lock: no live worker owns these.
    for path in output.glob("*/.rebuild-*"):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)


def prune_analyses(directory: Path, current: str) -> None:
    """Keep the published version and one previous completed version."""
    previous = [
        path
        for path in directory.iterdir()
        if path.name != current
        and len(path.name) == 32
        and all(c in "0123456789abcdef" for c in path.name)
        and not path.is_symlink()
        and (path / "metadata.json").is_file()
    ]
    previous.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    for path in previous[1:]:
        shutil.rmtree(path)


def rebuild(root: Path, output: Path, dataset_id: str) -> dict:
    cleanup_staging(output)
    directory = output / dataset_id
    directory.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".rebuild-", dir=directory) as temporary:
        staging = Path(temporary)
        metadata = evidence.build_bundle(root, dataset_id, staging)
        if metadata["status"] not in {"ready", "limited"}:
            raise ValueError("Recording source is not available")
        result = {"status": "completed", "analysis_id": metadata["analysis_id"]}
        try:
            publish(root, staging, dataset_id, metadata)
        except (OSError, ValueError, KeyError):
            logger.exception("Could not attach reviewed cases for %s", dataset_id)
            result["warning"] = "Evidence rebuilt, but reviewed cases could not be attached."
        destination = directory / metadata["analysis_id"]
        (staging / dataset_id / metadata["analysis_id"]).rename(destination)
        try:
            evidence.write_json(directory / "latest.json", {"analysis_id": metadata["analysis_id"]})
        except Exception:
            shutil.rmtree(destination)
            raise
    try:
        prune_analyses(directory, metadata["analysis_id"])
    except OSError:
        logger.exception("Could not prune previous analyses for %s", dataset_id)
        result["warning"] = "Evidence rebuilt, but older analyses could not be removed."
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset", required=True)
    args = parser.parse_args()
    try:
        result = rebuild(args.root, args.output, args.dataset)
    except PermissionError:
        logger.exception("Evidence output is not writable")
        result = {
            "status": "failed",
            "error": "Evidence storage is not writable. Check its ownership.",
        }
    except Exception:
        logger.exception("Evidence rebuild failed for %s", args.dataset)
        result = {"status": "failed", "error": "Could not rebuild evidence. Try again."}
    print(json.dumps(result), flush=True)
    if result["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
