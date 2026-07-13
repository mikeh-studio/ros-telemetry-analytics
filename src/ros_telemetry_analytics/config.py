from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_CONFIG_PATH = REPOSITORY_ROOT / "configs" / "pipeline.yaml"
PACKAGED_CONFIG_PATH = Path(__file__).with_name("default_pipeline.yaml")
DEFAULT_CONFIG_PATH = (
    REPOSITORY_CONFIG_PATH if REPOSITORY_CONFIG_PATH.exists() else PACKAGED_CONFIG_PATH
)
PROJECT_ROOT = REPOSITORY_ROOT if REPOSITORY_CONFIG_PATH.exists() else Path.cwd().resolve()


@dataclass(frozen=True)
class RateRule:
    pattern: str
    expected_rate_hz: float


@dataclass(frozen=True)
class AnalyticsConfig:
    rate_rules: tuple[RateRule, ...]
    gap_threshold_multiplier: float = 1.5
    minimum_rate_ratio: float = 0.8
    maximum_rate_ratio: float = 1.2
    continuity_topic_patterns: tuple[str, ...] = (
        r"^/tf$",
        r"^/tf_static$",
        r"pose",
        r"odom",
        r"visual_slam",
    )
    continuity_gap_ratio_warn: float = 3.0
    stereo_pairing_window_ns: int = 20_000_000
    stereo_skew_warn_ns: int = 5_000_000

    def expected_rate(self, topic: str) -> float | None:
        for rule in self.rate_rules:
            if re.search(rule.pattern, topic):
                return rule.expected_rate_hz
        return None

    def is_continuity_topic(self, topic: str) -> bool:
        return any(
            re.search(pattern, topic, re.IGNORECASE) for pattern in self.continuity_topic_patterns
        )


@dataclass(frozen=True)
class PipelineConfig:
    input_roots: tuple[Path, ...]
    output_root: Path
    excluded_directory_names: frozenset[str]
    parquet_batch_size: int
    analytics: AnalyticsConfig


def analytics_fingerprint(config: AnalyticsConfig) -> str:
    """Return a stable cache key for every setting that affects analytics output."""
    payload = {
        "analysis_engine_version": 1,
        "config": asdict(config),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _positive_number(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")
    return number


def _resolve_path(value: str | Path, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    return (base_dir / path).resolve() if not path.is_absolute() else path.resolve()


def load_pipeline_config(
    config_path: Path = DEFAULT_CONFIG_PATH,
    *,
    input_roots: list[Path] | None = None,
    output_root: Path | None = None,
) -> PipelineConfig:
    """Load and validate pipeline configuration, applying CLI path overrides."""
    config_path = config_path.expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as config_file:
        raw = yaml.safe_load(config_file) or {}

    pipeline_raw = raw.get("pipeline", {})
    analytics_raw = raw.get("analytics", {})
    configured_project_root = pipeline_raw.get("project_root")
    base_dir = (
        _resolve_path(configured_project_root, config_path.parent)
        if configured_project_root is not None
        else Path.cwd().resolve()
    )

    configured_inputs = input_roots or [
        Path(value) for value in pipeline_raw.get("input_roots", ["data/raw"])
    ]
    resolved_inputs = tuple(_resolve_path(path, base_dir) for path in configured_inputs)
    resolved_output = _resolve_path(
        output_root or pipeline_raw.get("output_root", "data/bronze"),
        base_dir,
    )

    rate_rules = tuple(
        RateRule(
            pattern=str(item["pattern"]),
            expected_rate_hz=_positive_number(item["expected_rate_hz"], "expected_rate_hz"),
        )
        for item in analytics_raw.get("expected_rates", [])
    )
    for rule in rate_rules:
        re.compile(rule.pattern)

    continuity_patterns = tuple(
        str(value)
        for value in analytics_raw.get(
            "continuity_topic_patterns",
            AnalyticsConfig(rate_rules=()).continuity_topic_patterns,
        )
    )
    for pattern in continuity_patterns:
        re.compile(pattern)

    analytics = AnalyticsConfig(
        rate_rules=rate_rules,
        gap_threshold_multiplier=_positive_number(
            analytics_raw.get("gap_threshold_multiplier", 1.5),
            "gap_threshold_multiplier",
        ),
        minimum_rate_ratio=_positive_number(
            analytics_raw.get("minimum_rate_ratio", 0.8),
            "minimum_rate_ratio",
        ),
        maximum_rate_ratio=_positive_number(
            analytics_raw.get("maximum_rate_ratio", 1.2),
            "maximum_rate_ratio",
        ),
        continuity_topic_patterns=continuity_patterns,
        continuity_gap_ratio_warn=_positive_number(
            analytics_raw.get("continuity_gap_ratio_warn", 3.0),
            "continuity_gap_ratio_warn",
        ),
        stereo_pairing_window_ns=int(
            _positive_number(
                analytics_raw.get("stereo_pairing_window_ms", 20.0),
                "stereo_pairing_window_ms",
            )
            * 1_000_000
        ),
        stereo_skew_warn_ns=int(
            _positive_number(
                analytics_raw.get("stereo_skew_warn_ms", 5.0),
                "stereo_skew_warn_ms",
            )
            * 1_000_000
        ),
    )

    batch_size = int(pipeline_raw.get("parquet_batch_size", 50_000))
    if batch_size < 1:
        raise ValueError("parquet_batch_size must be at least one")

    return PipelineConfig(
        input_roots=resolved_inputs,
        output_root=resolved_output,
        excluded_directory_names=frozenset(
            str(value) for value in pipeline_raw.get("excluded_directory_names", ["downloads"])
        ),
        parquet_batch_size=batch_size,
        analytics=analytics,
    )
