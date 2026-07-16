from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
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
class TopicRelationshipRule:
    name: str
    relationship_type: str
    topic_a: str
    topic_b: str
    required: bool = True
    pairing_window_ns: int | None = None
    skew_warn_ns: int | None = None


@dataclass(frozen=True)
class DomainAnalyticsConfig:
    enabled: bool = True
    command_topic_patterns: tuple[str, ...] = (r"cmd_vel", r"command")
    stationary_speed_threshold_mps: float = 0.05
    odometry_pose_jump_warn_m: float = 1.0
    imu_acceleration_warn_mps2: float = 30.0
    imu_angular_velocity_warn_rad_s: float = 10.0
    command_motion_threshold_mps: float = 0.1
    command_tracking_error_warn_mps: float = 0.5
    command_response_window_ns: int = 500_000_000
    tf_translation_jump_warn_m: float = 1.0
    image_dark_warn_mean: float = 20.0
    image_bright_warn_mean: float = 235.0
    image_sharpness_warn: float = 2.0
    event_merge_gap_ns: int = 500_000_000

    def is_command_topic(self, topic: str) -> bool:
        return any(
            re.search(pattern, topic, re.IGNORECASE) for pattern in self.command_topic_patterns
        )


@dataclass(frozen=True)
class AnalyticsConfig:
    rate_rules: tuple[RateRule, ...]
    topic_relationships: tuple[TopicRelationshipRule, ...] = ()
    domain: DomainAnalyticsConfig = field(default_factory=DomainAnalyticsConfig)
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
        "analysis_engine_version": 3,
        "config": asdict(config),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _positive_number(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")
    return number


def _nonnegative_number(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be finite and greater than or equal to zero")
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

    relationship_rows = analytics_raw.get("topic_relationships", [])
    if not isinstance(relationship_rows, list):
        raise ValueError("topic_relationships must be a list")
    topic_relationships: list[TopicRelationshipRule] = []
    relationship_names: set[str] = set()
    for item in relationship_rows:
        if not isinstance(item, dict):
            raise ValueError("each topic_relationships entry must be a mapping")
        name = str(item.get("name", "")).strip()
        relationship_type = str(item.get("type", "timestamp_pair")).strip()
        topic_a = str(item.get("topic_a", "")).strip()
        topic_b = str(item.get("topic_b", "")).strip()
        if not name:
            raise ValueError("topic relationship name must not be empty")
        if name in relationship_names:
            raise ValueError(f"duplicate topic relationship name: {name}")
        if relationship_type not in {"timestamp_pair", "stereo_sync"}:
            raise ValueError(f"topic relationship {name} has unsupported type: {relationship_type}")
        if not topic_a or not topic_b:
            raise ValueError(f"topic relationship {name} requires topic_a and topic_b")
        if topic_a == topic_b:
            raise ValueError(f"topic relationship {name} must reference two distinct topics")
        required = item.get("required", True)
        if not isinstance(required, bool):
            raise ValueError(f"topic relationship {name} required must be true or false")
        pairing_window_ms = item.get("pairing_window_ms")
        skew_warn_ms = item.get("skew_warn_ms")
        topic_relationships.append(
            TopicRelationshipRule(
                name=name,
                relationship_type=relationship_type,
                topic_a=topic_a,
                topic_b=topic_b,
                required=required,
                pairing_window_ns=(
                    int(
                        _positive_number(
                            pairing_window_ms,
                            f"topic relationship {name} pairing_window_ms",
                        )
                        * 1_000_000
                    )
                    if pairing_window_ms is not None
                    else None
                ),
                skew_warn_ns=(
                    int(
                        _positive_number(
                            skew_warn_ms,
                            f"topic relationship {name} skew_warn_ms",
                        )
                        * 1_000_000
                    )
                    if skew_warn_ms is not None
                    else None
                ),
            )
        )
        relationship_names.add(name)

    domain_raw = analytics_raw.get("domain_analyzers", {})
    if not isinstance(domain_raw, dict):
        raise ValueError("domain_analyzers must be a mapping")
    domain_enabled = domain_raw.get("enabled", True)
    if not isinstance(domain_enabled, bool):
        raise ValueError("domain_analyzers enabled must be true or false")
    patterns_raw = domain_raw.get(
        "command_topic_patterns",
        DomainAnalyticsConfig().command_topic_patterns,
    )
    if isinstance(patterns_raw, str) or not isinstance(patterns_raw, (list, tuple)):
        raise ValueError("command_topic_patterns must be a list of regular expressions")
    if any(not isinstance(value, str) or not value for value in patterns_raw):
        raise ValueError("command_topic_patterns entries must be non-empty strings")
    command_topic_patterns = tuple(patterns_raw)
    for pattern in command_topic_patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid command topic pattern {pattern!r}: {exc}") from exc
    domain = DomainAnalyticsConfig(
        enabled=domain_enabled,
        command_topic_patterns=command_topic_patterns,
        stationary_speed_threshold_mps=_nonnegative_number(
            domain_raw.get("stationary_speed_threshold_mps", 0.05),
            "stationary_speed_threshold_mps",
        ),
        odometry_pose_jump_warn_m=_positive_number(
            domain_raw.get("odometry_pose_jump_warn_m", 1.0),
            "odometry_pose_jump_warn_m",
        ),
        imu_acceleration_warn_mps2=_positive_number(
            domain_raw.get("imu_acceleration_warn_mps2", 30.0),
            "imu_acceleration_warn_mps2",
        ),
        imu_angular_velocity_warn_rad_s=_positive_number(
            domain_raw.get("imu_angular_velocity_warn_rad_s", 10.0),
            "imu_angular_velocity_warn_rad_s",
        ),
        command_motion_threshold_mps=_nonnegative_number(
            domain_raw.get("command_motion_threshold_mps", 0.1),
            "command_motion_threshold_mps",
        ),
        command_tracking_error_warn_mps=_nonnegative_number(
            domain_raw.get("command_tracking_error_warn_mps", 0.5),
            "command_tracking_error_warn_mps",
        ),
        command_response_window_ns=int(
            _positive_number(
                domain_raw.get("command_response_window_ms", 500.0),
                "command_response_window_ms",
            )
            * 1_000_000
        ),
        tf_translation_jump_warn_m=_positive_number(
            domain_raw.get("tf_translation_jump_warn_m", 1.0),
            "tf_translation_jump_warn_m",
        ),
        image_dark_warn_mean=_nonnegative_number(
            domain_raw.get("image_dark_warn_mean", 20.0),
            "image_dark_warn_mean",
        ),
        image_bright_warn_mean=_nonnegative_number(
            domain_raw.get("image_bright_warn_mean", 235.0),
            "image_bright_warn_mean",
        ),
        image_sharpness_warn=_nonnegative_number(
            domain_raw.get("image_sharpness_warn", 2.0),
            "image_sharpness_warn",
        ),
        event_merge_gap_ns=int(
            _positive_number(
                domain_raw.get("event_merge_gap_ms", 500.0),
                "event_merge_gap_ms",
            )
            * 1_000_000
        ),
    )
    if domain.image_dark_warn_mean >= domain.image_bright_warn_mean:
        raise ValueError("image_dark_warn_mean must be less than image_bright_warn_mean")

    analytics = AnalyticsConfig(
        rate_rules=rate_rules,
        topic_relationships=tuple(topic_relationships),
        domain=domain,
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
