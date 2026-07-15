from __future__ import annotations

from pathlib import Path

import pytest
from rosbags.rosbag2 import StoragePlugin, Writer
from rosbags.typesys import Stores, get_typestore

from ros_telemetry_analytics.config import AnalyticsConfig, RateRule


@pytest.fixture
def analytics_config() -> AnalyticsConfig:
    return AnalyticsConfig(
        rate_rules=(RateRule(r"/(?:image_raw|camera_info)$", 30.0),),
        stereo_pairing_window_ns=20_000_000,
        stereo_skew_warn_ns=5_000_000,
    )


@pytest.fixture
def write_bag():
    def _write(
        path: Path,
        messages: list[tuple[str, str, int]],
        storage_plugin: StoragePlugin = StoragePlugin.SQLITE3,
        empty_topics: list[tuple[str, str]] | None = None,
    ) -> Path:
        typestore = get_typestore(Stores.ROS2_HUMBLE)
        with Writer(path, version=9, storage_plugin=storage_plugin) as writer:
            connections = {}
            for topic, message_type in empty_topics or []:
                connections[(topic, message_type)] = writer.add_connection(
                    topic,
                    message_type,
                    typestore=typestore,
                )
            for topic, message_type, timestamp in messages:
                key = (topic, message_type)
                if key not in connections:
                    connections[key] = writer.add_connection(
                        topic,
                        message_type,
                        typestore=typestore,
                    )
                writer.write(connections[key], timestamp, b"raw-message")
        return path

    return _write


@pytest.fixture
def write_serialized_bag():
    def _write(
        path: Path,
        messages: list[tuple[str, object, int]],
        storage_plugin: StoragePlugin = StoragePlugin.SQLITE3,
    ) -> Path:
        typestore = get_typestore(Stores.ROS2_HUMBLE)
        with Writer(path, version=9, storage_plugin=storage_plugin) as writer:
            connections = {}
            for topic, message, timestamp in messages:
                message_type = message.__msgtype__
                key = (topic, message_type)
                if key not in connections:
                    connections[key] = writer.add_connection(
                        topic,
                        message_type,
                        typestore=typestore,
                    )
                rawdata = typestore.serialize_cdr(message, message_type)
                writer.write(connections[key], timestamp, rawdata)
        return path

    return _write
