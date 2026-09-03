from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from ros_telemetry_analytics.config import DomainAnalyticsConfig

DOMAIN_RECORD_DIRECTORY = "domain_records"

ODOMETRY_SCHEMA = pa.schema(
    [
        ("bag_id", pa.string()),
        ("sequence", pa.int64()),
        ("topic", pa.string()),
        ("timestamp_ns", pa.int64()),
        ("source_timestamp_ns", pa.int64()),
        ("frame_id", pa.string()),
        ("child_frame_id", pa.string()),
        ("position_x", pa.float64()),
        ("position_y", pa.float64()),
        ("position_z", pa.float64()),
        ("orientation_x", pa.float64()),
        ("orientation_y", pa.float64()),
        ("orientation_z", pa.float64()),
        ("orientation_w", pa.float64()),
        ("linear_x", pa.float64()),
        ("linear_y", pa.float64()),
        ("linear_z", pa.float64()),
        ("angular_x", pa.float64()),
        ("angular_y", pa.float64()),
        ("angular_z", pa.float64()),
        ("pose_covariance_trace", pa.float64()),
        ("twist_covariance_trace", pa.float64()),
    ]
)

IMU_SCHEMA = pa.schema(
    [
        ("bag_id", pa.string()),
        ("sequence", pa.int64()),
        ("topic", pa.string()),
        ("timestamp_ns", pa.int64()),
        ("source_timestamp_ns", pa.int64()),
        ("frame_id", pa.string()),
        ("orientation_x", pa.float64()),
        ("orientation_y", pa.float64()),
        ("orientation_z", pa.float64()),
        ("orientation_w", pa.float64()),
        ("angular_velocity_x", pa.float64()),
        ("angular_velocity_y", pa.float64()),
        ("angular_velocity_z", pa.float64()),
        ("linear_acceleration_x", pa.float64()),
        ("linear_acceleration_y", pa.float64()),
        ("linear_acceleration_z", pa.float64()),
        ("orientation_covariance_trace", pa.float64()),
        ("angular_velocity_covariance_trace", pa.float64()),
        ("linear_acceleration_covariance_trace", pa.float64()),
    ]
)

COMMAND_SCHEMA = pa.schema(
    [
        ("bag_id", pa.string()),
        ("sequence", pa.int64()),
        ("topic", pa.string()),
        ("timestamp_ns", pa.int64()),
        ("source_timestamp_ns", pa.int64()),
        ("frame_id", pa.string()),
        ("linear_x", pa.float64()),
        ("linear_y", pa.float64()),
        ("linear_z", pa.float64()),
        ("angular_x", pa.float64()),
        ("angular_y", pa.float64()),
        ("angular_z", pa.float64()),
    ]
)

TRANSFORM_SCHEMA = pa.schema(
    [
        ("bag_id", pa.string()),
        ("sequence", pa.int64()),
        ("topic", pa.string()),
        ("timestamp_ns", pa.int64()),
        ("source_timestamp_ns", pa.int64()),
        ("frame_id", pa.string()),
        ("child_frame_id", pa.string()),
        ("translation_x", pa.float64()),
        ("translation_y", pa.float64()),
        ("translation_z", pa.float64()),
        ("rotation_x", pa.float64()),
        ("rotation_y", pa.float64()),
        ("rotation_z", pa.float64()),
        ("rotation_w", pa.float64()),
    ]
)

DIAGNOSTIC_SCHEMA = pa.schema(
    [
        ("bag_id", pa.string()),
        ("sequence", pa.int64()),
        ("topic", pa.string()),
        ("timestamp_ns", pa.int64()),
        ("source_timestamp_ns", pa.int64()),
        ("frame_id", pa.string()),
        ("level", pa.int64()),
        ("name", pa.string()),
        ("message", pa.string()),
        ("hardware_id", pa.string()),
        ("values_json", pa.string()),
    ]
)

IMAGE_SCHEMA = pa.schema(
    [
        ("bag_id", pa.string()),
        ("sequence", pa.int64()),
        ("topic", pa.string()),
        ("timestamp_ns", pa.int64()),
        ("source_timestamp_ns", pa.int64()),
        ("frame_id", pa.string()),
        ("height", pa.int64()),
        ("width", pa.int64()),
        ("encoding", pa.string()),
        ("step", pa.int64()),
        ("data_bytes", pa.int64()),
        ("mean_intensity", pa.float64()),
        ("sharpness_score", pa.float64()),
        ("mean_depth_m", pa.float64()),
        ("valid_pixel_fraction", pa.float64()),
        ("content_hash", pa.string()),
    ]
)

LASER_SCAN_SCHEMA = pa.schema(
    [
        ("bag_id", pa.string()),
        ("sequence", pa.int64()),
        ("topic", pa.string()),
        ("timestamp_ns", pa.int64()),
        ("source_timestamp_ns", pa.int64()),
        ("frame_id", pa.string()),
        ("angle_min", pa.float64()),
        ("angle_max", pa.float64()),
        ("angle_increment", pa.float64()),
        ("scan_time_s", pa.float64()),
        ("range_min", pa.float64()),
        ("range_max", pa.float64()),
        ("beam_count", pa.int64()),
        ("finite_range_count", pa.int64()),
        ("valid_range_count", pa.int64()),
        ("below_min_count", pa.int64()),
        ("above_max_count", pa.int64()),
        ("intensity_count", pa.int64()),
        ("valid_range_fraction", pa.float64()),
        ("minimum_valid_range", pa.float64()),
        ("mean_valid_range", pa.float64()),
        ("maximum_valid_range", pa.float64()),
    ]
)

POINT_CLOUD_SCHEMA = pa.schema(
    [
        ("bag_id", pa.string()),
        ("sequence", pa.int64()),
        ("topic", pa.string()),
        ("timestamp_ns", pa.int64()),
        ("source_timestamp_ns", pa.int64()),
        ("frame_id", pa.string()),
        ("height", pa.int64()),
        ("width", pa.int64()),
        ("point_count", pa.int64()),
        ("field_count", pa.int64()),
        ("field_names_json", pa.string()),
        ("has_xyz", pa.bool_()),
        ("is_bigendian", pa.bool_()),
        ("point_step", pa.int64()),
        ("row_step", pa.int64()),
        ("data_bytes", pa.int64()),
        ("expected_data_bytes", pa.int64()),
        ("payload_complete", pa.bool_()),
        ("is_dense", pa.bool_()),
    ]
)

ANALYSIS_COVERAGE_SCHEMA = pa.schema(
    [
        ("bag_id", pa.string()),
        ("topic", pa.string()),
        ("message_type", pa.string()),
        ("message_count", pa.int64()),
        ("analysis_status", pa.string()),
        ("domain", pa.string()),
        ("analyzed_message_count", pa.int64()),
        ("extraction_error_count", pa.int64()),
        ("analysis_ratio", pa.float64()),
        ("detail", pa.string()),
    ]
)

EXTRACTION_ERROR_SCHEMA = pa.schema(
    [
        ("bag_id", pa.string()),
        ("sequence", pa.int64()),
        ("topic", pa.string()),
        ("message_type", pa.string()),
        ("timestamp_ns", pa.int64()),
        ("error_type", pa.string()),
        ("error_message", pa.string()),
    ]
)

DOMAIN_SCHEMAS = {
    "odometry": ODOMETRY_SCHEMA,
    "imu": IMU_SCHEMA,
    "commands": COMMAND_SCHEMA,
    "transforms": TRANSFORM_SCHEMA,
    "diagnostics": DIAGNOSTIC_SCHEMA,
    "images": IMAGE_SCHEMA,
    "laser_scans": LASER_SCAN_SCHEMA,
    "point_clouds": POINT_CLOUD_SCHEMA,
    "extraction_errors": EXTRACTION_ERROR_SCHEMA,
}

DOMAIN_RECORD_PATHS = {name: f"{DOMAIN_RECORD_DIRECTORY}/{name}.parquet" for name in DOMAIN_SCHEMAS}


def _stamp_ns(header: Any | None) -> int | None:
    if header is None:
        return None
    stamp = getattr(header, "stamp", None)
    if stamp is None:
        return None
    seconds = getattr(stamp, "sec", getattr(stamp, "secs", None))
    nanoseconds = getattr(stamp, "nanosec", getattr(stamp, "nsecs", None))
    if seconds is None or nanoseconds is None:
        return None
    return int(seconds) * 1_000_000_000 + int(nanoseconds)


def _frame_id(header: Any | None) -> str:
    return str(getattr(header, "frame_id", "") or "")


def _covariance_trace(values: Any, dimension: int) -> float | None:
    try:
        covariance = np.asarray(values, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError):
        return None
    indices = [index * dimension + index for index in range(dimension)]
    if covariance.size <= indices[-1]:
        return None
    trace = float(sum(covariance[index] for index in indices))
    return trace if math.isfinite(trace) else None


def _base_row(bag_id: str, sequence: int, topic: str, timestamp_ns: int) -> dict[str, Any]:
    return {
        "bag_id": bag_id,
        "sequence": sequence,
        "topic": topic,
        "timestamp_ns": timestamp_ns,
    }


def _odometry_row(
    bag_id: str,
    sequence: int,
    topic: str,
    timestamp_ns: int,
    message: Any,
) -> dict[str, Any]:
    pose = message.pose.pose
    twist = message.twist.twist
    return {
        **_base_row(bag_id, sequence, topic, timestamp_ns),
        "source_timestamp_ns": _stamp_ns(message.header),
        "frame_id": _frame_id(message.header),
        "child_frame_id": str(message.child_frame_id or ""),
        "position_x": float(pose.position.x),
        "position_y": float(pose.position.y),
        "position_z": float(pose.position.z),
        "orientation_x": float(pose.orientation.x),
        "orientation_y": float(pose.orientation.y),
        "orientation_z": float(pose.orientation.z),
        "orientation_w": float(pose.orientation.w),
        "linear_x": float(twist.linear.x),
        "linear_y": float(twist.linear.y),
        "linear_z": float(twist.linear.z),
        "angular_x": float(twist.angular.x),
        "angular_y": float(twist.angular.y),
        "angular_z": float(twist.angular.z),
        "pose_covariance_trace": _covariance_trace(message.pose.covariance, 6),
        "twist_covariance_trace": _covariance_trace(message.twist.covariance, 6),
    }


def _imu_row(
    bag_id: str,
    sequence: int,
    topic: str,
    timestamp_ns: int,
    message: Any,
) -> dict[str, Any]:
    return {
        **_base_row(bag_id, sequence, topic, timestamp_ns),
        "source_timestamp_ns": _stamp_ns(message.header),
        "frame_id": _frame_id(message.header),
        "orientation_x": float(message.orientation.x),
        "orientation_y": float(message.orientation.y),
        "orientation_z": float(message.orientation.z),
        "orientation_w": float(message.orientation.w),
        "angular_velocity_x": float(message.angular_velocity.x),
        "angular_velocity_y": float(message.angular_velocity.y),
        "angular_velocity_z": float(message.angular_velocity.z),
        "linear_acceleration_x": float(message.linear_acceleration.x),
        "linear_acceleration_y": float(message.linear_acceleration.y),
        "linear_acceleration_z": float(message.linear_acceleration.z),
        "orientation_covariance_trace": _covariance_trace(message.orientation_covariance, 3),
        "angular_velocity_covariance_trace": _covariance_trace(
            message.angular_velocity_covariance, 3
        ),
        "linear_acceleration_covariance_trace": _covariance_trace(
            message.linear_acceleration_covariance, 3
        ),
    }


def _command_row(
    bag_id: str,
    sequence: int,
    topic: str,
    timestamp_ns: int,
    message: Any,
    *,
    stamped: bool,
) -> dict[str, Any]:
    twist = message.twist if stamped else message
    header = message.header if stamped else None
    return {
        **_base_row(bag_id, sequence, topic, timestamp_ns),
        "source_timestamp_ns": _stamp_ns(header),
        "frame_id": _frame_id(header),
        "linear_x": float(twist.linear.x),
        "linear_y": float(twist.linear.y),
        "linear_z": float(twist.linear.z),
        "angular_x": float(twist.angular.x),
        "angular_y": float(twist.angular.y),
        "angular_z": float(twist.angular.z),
    }


def _transform_rows(
    bag_id: str,
    sequence: int,
    topic: str,
    timestamp_ns: int,
    message: Any,
    *,
    array_message: bool,
) -> list[dict[str, Any]]:
    transforms = message.transforms if array_message else [message]
    rows: list[dict[str, Any]] = []
    for transform_stamped in transforms:
        transform = transform_stamped.transform
        rows.append(
            {
                **_base_row(bag_id, sequence, topic, timestamp_ns),
                "source_timestamp_ns": _stamp_ns(transform_stamped.header),
                "frame_id": _frame_id(transform_stamped.header),
                "child_frame_id": str(transform_stamped.child_frame_id or ""),
                "translation_x": float(transform.translation.x),
                "translation_y": float(transform.translation.y),
                "translation_z": float(transform.translation.z),
                "rotation_x": float(transform.rotation.x),
                "rotation_y": float(transform.rotation.y),
                "rotation_z": float(transform.rotation.z),
                "rotation_w": float(transform.rotation.w),
            }
        )
    return rows


def _diagnostic_rows(
    bag_id: str,
    sequence: int,
    topic: str,
    timestamp_ns: int,
    message: Any,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for status in message.status:
        values = {str(value.key): str(value.value) for value in status.values}
        rows.append(
            {
                **_base_row(bag_id, sequence, topic, timestamp_ns),
                "source_timestamp_ns": _stamp_ns(message.header),
                "frame_id": _frame_id(message.header),
                "level": int(status.level),
                "name": str(status.name or ""),
                "message": str(status.message or ""),
                "hardware_id": str(status.hardware_id or ""),
                "values_json": json.dumps(values, sort_keys=True, separators=(",", ":")),
            }
        )
    return rows


def _image_statistics(
    message: Any,
) -> tuple[int, float | None, float | None, float | None, float | None, str]:
    data = np.asarray(message.data, dtype=np.uint8).reshape(-1)
    content_hash = hashlib.blake2b(memoryview(data), digest_size=8).hexdigest()
    data_bytes = int(data.nbytes)
    height = int(message.height)
    width = int(message.width)
    step = int(message.step)
    encoding = str(message.encoding or "").lower()
    channels = {
        "mono8": 1,
        "8uc1": 1,
        "rgb8": 3,
        "bgr8": 3,
        "rgba8": 4,
        "bgra8": 4,
    }.get(encoding)
    if height <= 0 or width <= 0 or step <= 0 or data.size < height * step:
        return data_bytes, None, None, None, None, content_hash

    byte_rows = data[: height * step].reshape(height, step)
    if encoding in {"mono16", "16uc1"}:
        active_width = width * 2
        if step < active_width:
            return data_bytes, None, None, None, None, content_hash
        byte_order = ">" if int(getattr(message, "is_bigendian", 0)) else "<"
        active = np.ascontiguousarray(byte_rows[:, :active_width])
        pixels_16 = np.frombuffer(active, dtype=f"{byte_order}u2").reshape(height, width)
        if encoding == "mono16":
            grayscale = pixels_16.astype(np.float32) / 257.0
            channels = 1
        else:
            valid = pixels_16 > 0
            valid_fraction = float(valid.mean())
            mean_depth_m = float(pixels_16[valid].mean() / 1000.0) if valid.any() else None
            return data_bytes, None, None, mean_depth_m, valid_fraction, content_hash
    elif encoding == "32fc1":
        active_width = width * 4
        if step < active_width:
            return data_bytes, None, None, None, None, content_hash
        byte_order = ">" if int(getattr(message, "is_bigendian", 0)) else "<"
        active = np.ascontiguousarray(byte_rows[:, :active_width])
        depth = np.frombuffer(active, dtype=f"{byte_order}f4").reshape(height, width)
        valid = np.isfinite(depth) & (depth > 0)
        valid_fraction = float(valid.mean())
        mean_depth_m = float(depth[valid].mean()) if valid.any() else None
        return data_bytes, None, None, mean_depth_m, valid_fraction, content_hash
    elif not channels:
        return data_bytes, None, None, None, None, content_hash
    else:
        active_width = width * channels
        if step < active_width:
            return data_bytes, None, None, None, None, content_hash
        pixels = byte_rows[:, :active_width].reshape(height, width, channels)
        grayscale = pixels[:, :, 0] if channels == 1 else pixels.mean(axis=2)

    sample_stride = max(1, max(height, width) // 256)
    sampled = grayscale[::sample_stride, ::sample_stride].astype(np.float32, copy=False)
    mean_intensity = float(sampled.mean()) if sampled.size else None
    differences: list[float] = []
    if sampled.shape[0] > 1:
        differences.append(float(np.abs(np.diff(sampled, axis=0)).mean()))
    if sampled.shape[1] > 1:
        differences.append(float(np.abs(np.diff(sampled, axis=1)).mean()))
    sharpness = sum(differences) / len(differences) if differences else None
    return data_bytes, mean_intensity, sharpness, None, None, content_hash


def _image_row(
    bag_id: str,
    sequence: int,
    topic: str,
    timestamp_ns: int,
    message: Any,
    *,
    compressed: bool,
) -> dict[str, Any]:
    if compressed:
        data = np.asarray(message.data, dtype=np.uint8).reshape(-1)
        data_bytes = int(data.nbytes)
        mean_intensity = None
        sharpness = None
        mean_depth_m = None
        valid_pixel_fraction = None
        content_hash = hashlib.blake2b(memoryview(data), digest_size=8).hexdigest()
        height = 0
        width = 0
        encoding = str(message.format or "")
        step = 0
    else:
        (
            data_bytes,
            mean_intensity,
            sharpness,
            mean_depth_m,
            valid_pixel_fraction,
            content_hash,
        ) = _image_statistics(message)
        height = int(message.height)
        width = int(message.width)
        encoding = str(message.encoding or "")
        step = int(message.step)
    return {
        **_base_row(bag_id, sequence, topic, timestamp_ns),
        "source_timestamp_ns": _stamp_ns(message.header),
        "frame_id": _frame_id(message.header),
        "height": height,
        "width": width,
        "encoding": encoding,
        "step": step,
        "data_bytes": data_bytes,
        "mean_intensity": mean_intensity,
        "sharpness_score": sharpness,
        "mean_depth_m": mean_depth_m,
        "valid_pixel_fraction": valid_pixel_fraction,
        "content_hash": content_hash,
    }


def _laser_scan_row(
    bag_id: str,
    sequence: int,
    topic: str,
    timestamp_ns: int,
    message: Any,
) -> dict[str, Any]:
    ranges = np.asarray(message.ranges, dtype=np.float64).reshape(-1)
    finite = np.isfinite(ranges)
    below_min = finite & (ranges < float(message.range_min))
    above_max = finite & (ranges > float(message.range_max))
    valid = finite & ~below_min & ~above_max
    valid_ranges = ranges[valid]
    beam_count = int(ranges.size)
    return {
        **_base_row(bag_id, sequence, topic, timestamp_ns),
        "source_timestamp_ns": _stamp_ns(message.header),
        "frame_id": _frame_id(message.header),
        "angle_min": float(message.angle_min),
        "angle_max": float(message.angle_max),
        "angle_increment": float(message.angle_increment),
        "scan_time_s": float(message.scan_time),
        "range_min": float(message.range_min),
        "range_max": float(message.range_max),
        "beam_count": beam_count,
        "finite_range_count": int(finite.sum()),
        "valid_range_count": int(valid.sum()),
        "below_min_count": int(below_min.sum()),
        "above_max_count": int(above_max.sum()),
        "intensity_count": int(np.asarray(message.intensities).size),
        "valid_range_fraction": float(valid.mean()) if beam_count else 0.0,
        "minimum_valid_range": float(valid_ranges.min()) if valid_ranges.size else None,
        "mean_valid_range": float(valid_ranges.mean()) if valid_ranges.size else None,
        "maximum_valid_range": float(valid_ranges.max()) if valid_ranges.size else None,
    }


def _point_cloud_row(
    bag_id: str,
    sequence: int,
    topic: str,
    timestamp_ns: int,
    message: Any,
) -> dict[str, Any]:
    height = int(message.height)
    width = int(message.width)
    row_step = int(message.row_step)
    data_bytes = int(np.asarray(message.data, dtype=np.uint8).size)
    fields = [str(field.name) for field in message.fields]
    normalized_fields = {name.lower() for name in fields}
    expected_data_bytes = max(0, height * row_step)
    return {
        **_base_row(bag_id, sequence, topic, timestamp_ns),
        "source_timestamp_ns": _stamp_ns(message.header),
        "frame_id": _frame_id(message.header),
        "height": height,
        "width": width,
        "point_count": max(0, height * width),
        "field_count": len(fields),
        "field_names_json": json.dumps(fields, separators=(",", ":")),
        "has_xyz": {"x", "y", "z"}.issubset(normalized_fields),
        "is_bigendian": bool(message.is_bigendian),
        "point_step": int(message.point_step),
        "row_step": row_step,
        "data_bytes": data_bytes,
        "expected_data_bytes": expected_data_bytes,
        "payload_complete": data_bytes >= expected_data_bytes,
        "is_dense": bool(message.is_dense),
    }


def message_kind(message_type: str) -> str | None:
    canonical = message_type.lower().replace("/msg/", "/")
    return {
        "nav_msgs/odometry": "odometry",
        "sensor_msgs/imu": "imu",
        "geometry_msgs/twiststamped": "twist_stamped",
        "geometry_msgs/twist": "twist",
        "tf2_msgs/tfmessage": "tf_message",
        "tf/tfmessage": "tf_message",
        "geometry_msgs/transformstamped": "transform_stamped",
        "diagnostic_msgs/diagnosticarray": "diagnostics",
        "sensor_msgs/compressedimage": "compressed_image",
        "sensor_msgs/image": "image",
        "sensor_msgs/laserscan": "laser_scan",
        "sensor_msgs/pointcloud2": "point_cloud",
    }.get(canonical)


def _kind_domain(kind: str | None) -> str:
    return {
        "odometry": "odometry",
        "imu": "imu",
        "twist": "command",
        "twist_stamped": "command",
        "tf_message": "tf",
        "transform_stamped": "tf",
        "diagnostics": "diagnostics",
        "image": "image",
        "compressed_image": "image",
        "laser_scan": "laser_scan",
        "point_cloud": "point_cloud",
    }.get(kind, "unclassified")


class DomainRecordWriter:
    """Stream selected ROS payload fields into bounded, typed Parquet datasets."""

    def __init__(
        self,
        output_dir: Path,
        bag_id: str,
        config: DomainAnalyticsConfig,
        batch_size: int,
    ) -> None:
        self.output_dir = output_dir / DOMAIN_RECORD_DIRECTORY
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.bag_id = bag_id
        self.config = config
        self.batch_size = batch_size
        self.buffers: dict[str, list[dict[str, Any]]] = {name: [] for name in DOMAIN_SCHEMAS}
        self.writers: dict[str, pq.ParquetWriter] = {}
        self.analyzed_counts: dict[tuple[str, str], int] = {}
        self.error_counts: dict[tuple[str, str], int] = {}

    def _add(self, dataset: str, row: dict[str, Any]) -> None:
        self.buffers[dataset].append(row)
        if len(self.buffers[dataset]) >= self.batch_size:
            self._flush(dataset)

    def _flush(self, dataset: str) -> None:
        rows = self.buffers[dataset]
        if not rows:
            return
        writer = self.writers.get(dataset)
        if writer is None:
            writer = pq.ParquetWriter(
                self.output_dir / f"{dataset}.parquet",
                DOMAIN_SCHEMAS[dataset],
                compression="zstd",
            )
            self.writers[dataset] = writer
        writer.write_table(pa.Table.from_pylist(rows, schema=DOMAIN_SCHEMAS[dataset]))
        rows.clear()

    def process(
        self,
        reader: Any,
        connection: Any,
        sequence: int,
        timestamp_ns: int,
        rawdata: bytes,
    ) -> None:
        if not self.config.enabled:
            return
        kind = message_kind(connection.msgtype)
        if kind in {"twist", "twist_stamped"} and not self.config.is_command_topic(
            connection.topic
        ):
            return
        if kind is None:
            return

        try:
            message = reader.deserialize(rawdata, connection.msgtype)
            if kind == "odometry":
                self._add(
                    "odometry",
                    _odometry_row(self.bag_id, sequence, connection.topic, timestamp_ns, message),
                )
            elif kind == "imu":
                self._add(
                    "imu",
                    _imu_row(self.bag_id, sequence, connection.topic, timestamp_ns, message),
                )
            elif kind in {"twist", "twist_stamped"}:
                self._add(
                    "commands",
                    _command_row(
                        self.bag_id,
                        sequence,
                        connection.topic,
                        timestamp_ns,
                        message,
                        stamped=kind == "twist_stamped",
                    ),
                )
            elif kind in {"tf_message", "transform_stamped"}:
                for row in _transform_rows(
                    self.bag_id,
                    sequence,
                    connection.topic,
                    timestamp_ns,
                    message,
                    array_message=kind == "tf_message",
                ):
                    self._add("transforms", row)
            elif kind == "diagnostics":
                for row in _diagnostic_rows(
                    self.bag_id, sequence, connection.topic, timestamp_ns, message
                ):
                    self._add("diagnostics", row)
            elif kind in {"image", "compressed_image"}:
                self._add(
                    "images",
                    _image_row(
                        self.bag_id,
                        sequence,
                        connection.topic,
                        timestamp_ns,
                        message,
                        compressed=kind == "compressed_image",
                    ),
                )
            elif kind == "laser_scan":
                self._add(
                    "laser_scans",
                    _laser_scan_row(self.bag_id, sequence, connection.topic, timestamp_ns, message),
                )
            elif kind == "point_cloud":
                self._add(
                    "point_clouds",
                    _point_cloud_row(
                        self.bag_id, sequence, connection.topic, timestamp_ns, message
                    ),
                )
            key = (connection.topic, connection.msgtype)
            self.analyzed_counts[key] = self.analyzed_counts.get(key, 0) + 1
        except Exception as exc:
            key = (connection.topic, connection.msgtype)
            self.error_counts[key] = self.error_counts.get(key, 0) + 1
            self._add(
                "extraction_errors",
                {
                    **_base_row(self.bag_id, sequence, connection.topic, timestamp_ns),
                    "message_type": connection.msgtype,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:500],
                },
            )

    def close(self, topic_counts: dict[tuple[str, str], int] | None = None) -> None:
        for dataset in DOMAIN_SCHEMAS:
            self._flush(dataset)
        for writer in self.writers.values():
            writer.close()
        for dataset, schema in DOMAIN_SCHEMAS.items():
            path = self.output_dir / f"{dataset}.parquet"
            if not path.exists():
                pq.write_table(pa.Table.from_pylist([], schema=schema), path, compression="zstd")
        coverage_rows: list[dict[str, Any]] = []
        for (topic, message_type), message_count in sorted((topic_counts or {}).items()):
            kind = message_kind(message_type)
            command_filtered = kind in {
                "twist",
                "twist_stamped",
            } and not self.config.is_command_topic(topic)
            analyzed_count = self.analyzed_counts.get((topic, message_type), 0)
            error_count = self.error_counts.get((topic, message_type), 0)
            if not self.config.enabled:
                status = "disabled"
                detail = "Payload analysis is disabled; timing analysis remains available."
            elif kind is None:
                status = "timing_only"
                detail = "No payload analyzer is registered for this message type."
            elif command_filtered:
                status = "timing_only"
                detail = "Twist payload was not selected by the command-topic patterns."
            elif not message_count:
                status = "no_messages"
                detail = "The bag declared this topic/type but contained no messages."
            elif analyzed_count == message_count and not error_count:
                status = "full"
                detail = "Every message was processed by the registered payload analyzer."
            elif analyzed_count:
                status = "partial"
                detail = "Some messages could not be processed by the payload analyzer."
            else:
                status = "failed"
                detail = "No messages could be processed by the registered payload analyzer."
            coverage_rows.append(
                {
                    "bag_id": self.bag_id,
                    "topic": topic,
                    "message_type": message_type,
                    "message_count": message_count,
                    "analysis_status": status,
                    "domain": _kind_domain(kind),
                    "analyzed_message_count": analyzed_count,
                    "extraction_error_count": error_count,
                    "analysis_ratio": (analyzed_count / message_count if message_count else None),
                    "detail": detail,
                }
            )
        pq.write_table(
            pa.Table.from_pylist(coverage_rows, schema=ANALYSIS_COVERAGE_SCHEMA),
            self.output_dir.parent / "analysis_coverage.parquet",
            compression="zstd",
        )
