from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlencode

import jsonschema
import numpy as np
import polars as pl
import pytest
import yaml
from fastapi import FastAPI
from rosbags.rosbag2 import StoragePlugin
from test_investigations import image

from demo.api.recording_investigation import router
from ros_telemetry_analytics import incident_explanations as engine
from ros_telemetry_analytics import investigations as evidence
from ros_telemetry_analytics.config import DomainAnalyticsConfig
from ros_telemetry_analytics.domain_analysis import _analyze_commands
from ros_telemetry_analytics.incident_grouping import normalize_events


@pytest.fixture
def bundle(tmp_path, write_serialized_bag):
    messages = []
    for n in range(10):
        sample = image(n)
        if n in {3, 4}:
            sample.data = np.zeros(4, dtype=np.uint8)
        messages.append(("/camera", sample, n * 100_000_000))
    bag = write_serialized_bag(tmp_path / "bag", messages, storage_plugin=StoragePlugin.MCAP)
    source = next(bag.glob("*.mcap"))
    config = tmp_path / "configs"
    config.mkdir()
    (config / "profile.yaml").write_text("""pipeline:
  project_root: ..
analytics:
  expected_rates:
    - pattern: ^/camera$
      expected_rate_hz: 10
""")
    spec = {
        "name": "Test",
        "input": str(source.relative_to(tmp_path)),
        "profile": "configs/profile.yaml",
        "role": "real_recording",
        "purpose": "test",
        "source": "https://example.test",
        "license": "test",
    }
    (config / "investigations.yaml").write_text(yaml.safe_dump({"datasets": {"test": spec}}))
    output = tmp_path / "prepared"
    metadata = evidence.build_bundle(tmp_path, "test", output)
    directory, _ = evidence.load_bundle(tmp_path, output, "test")
    return tmp_path, output, directory, metadata


def test_image_explanation_reconciles_source_evidence_and_schema(bundle):
    root, _, directory, metadata = bundle
    document = evidence.incident_document(directory, metadata)
    assert document["incidents"]
    incident = next(i for i in document["incidents"] if len(i["member_event_ids"]) == 2)
    dark = next(o for o in incident["observations"] if o["rule_id"] == "dark_frames")
    assert dark["parameters"]["sample_count"] == 2
    assert dark["parameters"]["analyzed_count"] == 2
    assert dark["parameters"]["threshold"] == 20
    assert any(
        o["rule_id"] == "delivery_context" and o["parameters"]["exceedance_count"] == 0
        for o in incident["observations"]
    )
    assert all(p["status"] == "untested" for p in incident["possibilities"])
    assert incident["explanation_status"] == "supported"
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/recording-incidents-v1.schema.json").read_text()
    )
    jsonschema.validate(document, schema)
    # Rebuilding from full saved events is independent of publication identity.
    repeated = engine.build_incidents(
        root, directory, metadata, evidence.event_records(directory, metadata)
    )
    assert repeated == document


def test_complete_events_paginated_fallback_and_missing_provenance(bundle):
    root, _, directory, metadata = bundle
    original = next(
        e for e in evidence.event_records(directory, metadata) if e["event_type"] == "dark_frames"
    )
    events = [
        {
            **original,
            "event_type": "future_detector",
            "start_timestamp_ns": str(i),
            "end_timestamp_ns": str(i),
            "start_s": i / 1e9,
            "end_s": i / 1e9,
        }
        for i in range(251)
    ]
    document = engine.build_incidents(root, directory, metadata, events)
    evidence.write_json(directory / "incidents.json", document)
    metadata["incident_artifacts"]["incidents.json"] = evidence.sha256(directory / "incidents.json")
    assert len(document["incidents"]) == 251
    assert all(i["explanation_status"] == "unsupported" for i in document["incidents"])
    assert all(i["possibilities"] == [] for i in document["incidents"])
    page = evidence.incident_list(directory, metadata, offset=200, limit=100)
    assert page["total_count"] == 251 and page["returned_count"] == 51
    with pytest.raises(ValueError):
        evidence.incident_list(directory, metadata, start_s=0)
    # Known type whose input provenance does not match must not invent an explanation.
    changed = {**original, "threshold": 99.0}
    missing = engine.build_incidents(root, directory, metadata, [changed])
    assert missing["incidents"][0]["explanation_status"] == "insufficient_evidence"


def test_validation_rejects_dangling_evidence_and_membership(bundle):
    _, _, directory, metadata = bundle
    document = evidence.incident_document(directory, metadata)
    events = evidence.event_records(directory, metadata)
    for mutate in [
        lambda d: d["incidents"][0]["observations"][0].update(evidence_refs=["missing"]),
        lambda d: d["incidents"][0].update(member_event_ids=["missing"]),
        lambda d: d.update(analysis_id="other"),
    ]:
        changed = deepcopy(document)
        mutate(changed)
        with pytest.raises(ValueError):
            engine.validate(changed, events, metadata)


def test_catalog_and_artifact_changes_are_stale_and_failed_publication_preserves_pointer(
    bundle, monkeypatch
):
    root, output, directory, metadata = bundle
    previous = (output / "test/latest.json").read_bytes()
    monkeypatch.setattr(
        engine, "build_incidents", lambda *a: (_ for _ in ()).throw(ValueError("failure"))
    )
    with pytest.raises(ValueError, match="failure"):
        evidence.build_bundle(root, "test", output)
    assert (output / "test/latest.json").read_bytes() == previous
    (directory / "incidents.json").write_text("{}")
    with pytest.raises(ValueError, match="artifact changed"):
        evidence.load_bundle(root, output, "test")
    (root / engine.CATALOG).write_text("max_group_span_s: 5\n")
    with pytest.raises(ValueError, match="stale"):
        evidence.load_bundle(root, output, "test")
    (root / engine.CATALOG).write_text("max_group_span_s: .nan\n")
    with pytest.raises(ValueError, match="Invalid"):
        engine.catalog(root)


def test_delivery_needs_boundary_coverage_and_retains_duplicates():
    index = pl.DataFrame(
        {"topic": ["/camera"] * 4, "timestamp_ns": [0, 0, 100, 1000], "sequence": [0, 1, 2, 3]}
    )
    metadata = {"topic_health": [{"topic": "/camera", "gap_threshold_s": 0.0000002}]}
    result = engine._delivery(index, metadata, "/camera", 50, 500)
    assert result["parameters"]["exceedance_count"] == 1
    assert result["parameters"]["pair_count"] == 2
    assert engine._delivery(index, metadata, "/camera", 0, 1100)["availability"] == "unavailable"
    assert (
        engine._delivery(index, {"topic_health": []}, "/camera", 0, 100)["availability"]
        == "unavailable"
    )


def test_motion_keeps_actual_nearest_match_and_second_threshold():
    common = {
        "bag_id": "bag",
        "linear_y": 0.0,
        "linear_z": 0.0,
        "angular_x": 0.0,
        "angular_y": 0.0,
        "angular_z": 0.0,
        "frame_id": "",
    }
    commands = pl.DataFrame(
        [{**common, "topic": "/cmd", "sequence": 1, "timestamp_ns": 100_000_000, "linear_x": 0.2}]
    )
    odometry = pl.DataFrame(
        [
            {
                **common,
                "topic": "/odom",
                "sequence": 2,
                "timestamp_ns": 90_000_000,
                "linear_x": 0.0,
                "child_frame_id": "base",
            }
        ]
    )
    events = []
    _analyze_commands(commands, odometry, DomainAnalyticsConfig(), [], events)
    event = next(e for e in events if e["event_type"] == "command_without_motion")
    p = event["_provenance"]
    assert p["sample_count"] == 1 and p["stationary_threshold_mps"] == 0.05
    assert p["matches"][0]["offset_ns"] == "-10000000"
    assert p["matches"][0]["odometry_sequence"] == 2
    normalized = normalize_events([event], "source")[0]
    observation, ref = engine._event_observation(normalized, p)
    assert observation["parameters"]["minimum_offset_ms"] == -10
    assert "nearest" in observation["text"]
    assert ref["selection"]["count"] == 1


def request(app, path, params=None):
    async def call():
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await app(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": urlencode(params or {}).encode(),
                "headers": [],
                "client": ("test", 1),
                "server": ("test", 80),
                "root_path": "",
            },
            receive,
            send,
        )
        return messages[0]["status"], json.loads(b"".join(m.get("body", b"") for m in messages))

    return asyncio.run(call())


def test_real_api_exposes_incidents_and_targeted_evidence(bundle):
    root, output, _, metadata = bundle
    app = FastAPI()
    app.include_router(router(root, output))
    prefix = "/api/investigations/test"
    params = {"analysis_id": metadata["analysis_id"]}
    status, page = request(app, prefix + "/incidents", params)
    assert status == 200 and page["total_count"] > 0
    incident_id = page["incidents"][0]["incident_id"]
    status, detail = request(app, prefix + "/incidents/" + incident_id, params)
    assert status == 200 and detail["source_sha256"] == metadata["source_sha256"]
    assert detail["member_events"] and "member_event_ids" not in detail
    assert request(app, prefix + "/incidents/missing", params)[0] == 404
    assert request(app, prefix + "/incidents", {**params, "analysis_id": "f" * 32})[0] == 409
    assert request(app, prefix + "/incidents", {**params, "limit": 101})[0] == 422
    assert request(app, prefix + "/incidents", {**params, "start_s": 0})[0] == 400
    status, data = request(
        app,
        prefix + "/interval",
        {**params, "start_s": 0, "end_s": 0.9, "topic": "/camera", "field": "mean_intensity"},
    )
    assert status == 200 and len(data["series"]) == 1
    assert data["series"][0]["field"] == "mean_intensity"
    assert (
        request(
            app, prefix + "/interval", {**params, "start_s": 0, "end_s": 0.9, "field": "secret"}
        )[0]
        == 400
    )


def test_reference_gap_keeps_boundary_evidence(bundle):
    root, _, directory, metadata = bundle
    event = {
        "bag_id": "bag",
        "domain": "timing",
        "topic": "/camera",
        "severity": "warn",
        "start_timestamp_ns": "200000000",
        "end_timestamp_ns": "300000000",
        "start_s": 0.2,
        "end_s": 0.3,
        "event_type": "reference_gap",
        "observed_value": 100.0,
        "threshold": 50.0,
        "unit": "ms",
        "detail": "reference gap",
    }
    doc = engine.build_incidents(root, directory, metadata, [event])
    incident = doc["incidents"][0]
    assert incident["family"] == "reference_gap"
    assert incident["observations"][0]["parameters"]["reference_context"] is True
    assert incident["evidence"][0]["selection"]["count"] == 2
    assert "not evidence of camera or IMU failure" in incident["limits"][0]
    # A narrow view inside a gap still includes the event whose boundaries are outside the view.
    result = evidence.interval(directory, metadata, 0.22, 0.28)
    assert result["event_count"] == 1


def test_more_than_sixty_series_still_allows_exact_signal_selection(bundle):
    _, _, directory, metadata = bundle
    path = directory / metadata["analysis_path"] / "domain_records/images.parquet"
    frame = pl.read_parquet(path)
    frames = [frame.with_columns(pl.lit(f"/camera{i}").alias("topic")) for i in range(65)]
    pl.concat(frames).write_parquet(path)
    metadata["coverage"] = [{"topic": f"/camera{i}"} for i in range(65)]
    overview = evidence.interval(directory, metadata, 0, 0.9)
    assert overview["series_count"] > 60 and overview["series_truncated"]
    selected = evidence.interval(directory, metadata, 0, 0.9, "/camera64", "mean_intensity")
    assert len(selected["series"]) == 1 and not selected["series_truncated"]
    assert selected["series"][0]["topic"] == "/camera64"


def test_related_camera_is_context_only_and_counts_are_checked(bundle):
    root, _, directory, metadata = bundle
    path = directory / metadata["analysis_path"] / "domain_records/images.parquet"
    frame = pl.read_parquet(path)
    pl.concat([frame, frame.with_columns(pl.lit("/other").alias("topic"))]).write_parquet(path)
    metadata["relationships"] = [
        {
            "source": "configured",
            "relationship_name": "stereo",
            "topic_a": "/camera",
            "topic_b": "/other",
        }
    ]
    doc = engine.build_incidents(
        root, directory, metadata, evidence.event_records(directory, metadata)
    )
    incident = next(i for i in doc["incidents"] if i["family"] == "image_content")
    context = next(e for e in incident["evidence"] if e["kind"] == "related_context")
    assert context["topic"] == "/other" and "no shared cause inferred" in context["reason"]
    assert incident["topics"] == ["/camera"]
    sidecar = pl.read_parquet(directory / "event_evidence.parquet").to_dicts()
    raw = next(
        json.loads(row["evidence_json"])
        for row in sidecar
        if json.loads(row["evidence_json"]) is not None
    )
    raw["sample_count"] += 1
    event = next(
        e for e in evidence.event_records(directory, metadata) if e["event_type"] == "dark_frames"
    )
    with pytest.raises(ValueError, match="counts"):
        engine.validate_provenance(event, raw)


def test_full_motion_explanation_preserves_frames_and_available_next_checks(bundle):
    from ros_telemetry_analytics.incident_grouping import event_key

    root, _, directory, metadata = bundle
    analysis = directory / metadata["analysis_path"]
    frames = {}
    for domain, topic in (("commands", "/cmd"), ("odometry", "/odom")):
        path = analysis / f"domain_records/{domain}.parquet"
        schema = pl.read_parquet(path).schema
        row = {
            "bag_id": "bag",
            "topic": topic,
            "sequence": 42 if domain == "commands" else 43,
            "timestamp_ns": 300_000_000 if domain == "commands" else 290_000_000,
            "linear_x": 0.2 if domain == "commands" else 0.0,
            "linear_y": 0.0,
            "linear_z": 0.0,
            "angular_x": 0.0,
            "angular_y": 0.0,
            "angular_z": 0.1,
            "frame_id": "",
            "child_frame_id": "base",
        }
        frames[domain] = pl.DataFrame([row], schema=schema)
        frames[domain].write_parquet(path)
        metadata["coverage"].append({"topic": topic, "extraction_error_count": 0})
    events = []
    _analyze_commands(frames["commands"], frames["odometry"], DomainAnalyticsConfig(), [], events)
    event = next(e for e in events if e["event_type"] == "command_without_motion")
    p = event.pop("_provenance")
    pl.DataFrame([{"event_key": event_key(event), "evidence_json": json.dumps(p)}]).write_parquet(
        analysis / "anomaly_event_evidence.parquet"
    )
    event.update(start_s=0.3, end_s=0.3)
    document = engine.build_incidents(root, directory, metadata, [event])
    incident = document["incidents"][0]
    assert incident["explanation_status"] == "supported"
    assert incident["observations"][0]["parameters"]["minimum_offset_ms"] == -10
    assert incident["observations"][0]["parameters"]["odometry_frames"] == ["base"]
    assert len([c for c in incident["next_checks"] if c["availability"] == "available"]) == 2
    assert any(e["field"] == "angular_z" and e["topic"] == "/odom" for e in incident["evidence"])
