from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from ros_telemetry_analytics.assets import download_asset, load_asset_config
from ros_telemetry_analytics.config import DEFAULT_CONFIG_PATH, load_pipeline_config
from ros_telemetry_analytics.discovery import discover_bags
from ros_telemetry_analytics.localization_eval import (
    LocalizationEvalConfig,
    evaluate_localization_files,
)
from ros_telemetry_analytics.pipeline import run_pipeline


def _path(value: str) -> Path:
    return Path(value).expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ros-telemetry",
        description="Discover and analyze ROS bag telemetry without a ROS installation.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable detailed logs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser("discover", help="List canonical ROS bag inputs.")
    discover.add_argument("--config", type=_path, default=DEFAULT_CONFIG_PATH)
    discover.add_argument("--input", type=_path, action="append", dest="inputs")

    analyze = subparsers.add_parser("analyze", help="Discover, ingest, and analyze all bags.")
    analyze.add_argument("--config", type=_path, default=DEFAULT_CONFIG_PATH)
    analyze.add_argument("--input", type=_path, action="append", dest="inputs")
    analyze.add_argument("--output", type=_path)
    analyze.add_argument("--force", action="store_true", help="Reprocess unchanged bags.")
    analyze.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first bag failure.",
    )

    assets = subparsers.add_parser("download", help="Download configured NVIDIA sample assets.")
    selection = assets.add_mutually_exclusive_group(required=True)
    selection.add_argument("--asset", help="Configured asset key to download.")
    selection.add_argument("--all", action="store_true", help="Download every configured asset.")

    localization = subparsers.add_parser(
        "evaluate-localization",
        help="Evaluate an observable-only localization detector against TUHH labels.",
    )
    localization.add_argument(
        "--input",
        type=_path,
        action="append",
        dest="inputs",
        required=True,
        help="Extracted TUHH processed Parquet member; repeat for multiple members.",
    )
    localization.add_argument("--output", type=_path, required=True)
    localization.add_argument("--particle-spread-threshold-m", type=float, default=0.4)
    localization.add_argument("--pose-jump-threshold-m", type=float, default=0.5)
    localization.add_argument("--event-merge-gap-ms", type=float, default=500.0)
    localization.add_argument("--event-tolerance-ms", type=float, default=100.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if args.command == "download":
        assets = load_asset_config()
        selected = list(assets) if args.all else [args.asset]
        unknown = [name for name in selected if name not in assets]
        if unknown:
            raise SystemExit(f"Unknown asset(s): {', '.join(unknown)}")
        for name in selected:
            output = download_asset(name, assets[name])
            print(f"{name}: {output}")
        return 0

    if args.command == "evaluate-localization":
        summary = evaluate_localization_files(
            args.inputs,
            args.output,
            LocalizationEvalConfig(
                particle_spread_warn_m=args.particle_spread_threshold_m,
                pose_jump_warn_m=args.pose_jump_threshold_m,
                event_merge_gap_ms=args.event_merge_gap_ms,
                event_tolerance_ms=args.event_tolerance_ms,
            ),
        )
        print(json.dumps(summary, indent=2))
        return 0

    config = load_pipeline_config(
        args.config,
        input_roots=args.inputs,
        output_root=getattr(args, "output", None),
    )
    if args.command == "discover":
        sources = discover_bags(config.input_roots, config.excluded_directory_names)
        print(json.dumps([source.to_dict() for source in sources], indent=2))
        return 0

    manifest = run_pipeline(config, force=args.force, fail_fast=args.fail_fast)
    print(json.dumps(manifest, indent=2))
    return 1 if manifest["failed_count"] or manifest["discovered_count"] == 0 else 0
