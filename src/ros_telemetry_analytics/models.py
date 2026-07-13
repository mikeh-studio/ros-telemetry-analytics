from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BagSource:
    """A canonical ROS bag input discovered on disk."""

    bag_id: str
    path: Path
    format: str
    container: str
    size_bytes: int
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["path"] = str(self.path)
        return row


@dataclass(frozen=True)
class ProcessResult:
    """Outcome for one bag in a pipeline run."""

    bag_id: str
    status: str
    source_path: str
    fingerprint: str
    output_path: str | None = None
    message_count: int = 0
    topic_count: int = 0
    health_status: str | None = None
    warning_count: int = 0
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
