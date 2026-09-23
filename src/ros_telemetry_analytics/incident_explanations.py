"""Offline explanations from reviewed rules and exact detector evidence, without a model."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TypedDict

import polars as pl
import yaml

from ros_telemetry_analytics.incident_grouping import (
    GROUPING_VERSION,
    digest,
    family,
    group_events,
    normalize_events,
)

CATALOG = "configs/incident_explanations.yaml"
ARTIFACTS = ("events.parquet", "event_evidence.parquet", "incidents.json")


class Observation(TypedDict):
    rule_id: str
    text: str
    evidence_refs: list[str]
    parameters: dict


class Incident(TypedDict):
    incident_id: str
    family: str
    title: str
    member_event_ids: list[str]
    observations: list[Observation]
    evidence: list[dict]


def catalog(root: Path) -> dict:
    result = yaml.safe_load(
        Path(__file__).with_name("default_incident_explanations.yaml").read_text()
    )
    path = root / CATALOG
    override = yaml.safe_load(path.read_text()) if path.exists() else {}
    if not isinstance(override, dict) or set(override) - set(result):
        raise ValueError("Invalid incident catalog fields")
    result.update(override)
    if result["schema_version"] != 1 or not isinstance(result["catalog_version"], str):
        raise ValueError("Unsupported incident catalog version")
    for key in ("max_group_span_s", "context_padding_s"):
        value = result[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"Invalid incident catalog {key}")
        if not 0 < value <= 60:
            raise ValueError(f"Incident catalog {key} must be in (0, 60]")
    expected = {
        "image_content",
        "recorded_gap",
        "reference_gap",
        "motion_disagreement",
        "unsupported",
    }
    if not isinstance(result["families"], dict) or set(result["families"]) != expected:
        raise ValueError("Invalid incident families")
    for entry in result["families"].values():
        if (
            not isinstance(entry, dict)
            or set(entry) != {"title", "possibilities", "limits", "next_check"}
            or any(
                not isinstance(entry[k], str) or not entry[k]
                for k in ("title", "limits", "next_check")
            )
            or not isinstance(entry["possibilities"], list)
            or any(not isinstance(p, str) for p in entry["possibilities"])
        ):
            raise ValueError("Invalid incident explanation definition")
    return result


def _selection(samples: list[dict]) -> dict:
    return {
        "count": len(samples),
        "sha256": digest(samples),
        "examples": samples[:3],
        "examples_truncated": len(samples) > 3,
    }


def _gap_evidence(event: dict, index: pl.DataFrame) -> dict:
    stamps = index.filter(pl.col("topic") == event["topic"])
    bounds = {int(event["start_timestamp_ns"]), int(event["end_timestamp_ns"])}
    rows = stamps.filter(pl.col("timestamp_ns").is_in(list(bounds))).sort("sequence").to_dicts()
    return {
        "kind": "gap",
        "sample_count": len(rows),
        "clock": "recorded_receive",
        "boundary_samples": [
            {"sequence": r["sequence"], "timestamp_ns": str(r["timestamp_ns"])} for r in rows
        ],
        "threshold_ms": event["threshold"],
        "observed_ms": event["observed_value"],
        "reference_context": event["event_type"] == "reference_gap",
    }


def _delivery(index: pl.DataFrame, metadata: dict, topic: str, lo: int, hi: int) -> dict:
    health = next((r for r in metadata["topic_health"] if r["topic"] == topic), {})
    threshold = health.get("gap_threshold_s")
    stamps = index.filter(pl.col("topic") == topic).sort(["timestamp_ns", "sequence"])
    times = stamps["timestamp_ns"].to_list()
    pairs = [(a, b) for a, b in zip(times, times[1:], strict=False) if a <= hi and b >= lo]
    available = bool(threshold and len(times) >= 2 and times[0] <= lo and times[-1] >= hi and pairs)
    return {
        "id": f"delivery:{topic}",
        "kind": "delivery_context",
        "topic": topic,
        "field": "inter_message_gap_ms",
        "unit": "ms",
        "clock": "recorded_receive",
        "start_timestamp_ns": str(lo),
        "end_timestamp_ns": str(hi),
        "availability": "available" if available else "unavailable",
        "reason": "Complete boundary coverage and configured threshold"
        if available
        else "Missing configured threshold or recording boundary coverage",
        "parameters": {
            "pair_count": len(pairs),
            "threshold_ms": threshold * 1000 if threshold else None,
            "maximum_ms": max((b - a) / 1e6 for a, b in pairs) if pairs else None,
            "exceedance_count": sum((b - a) / 1e9 > threshold for a, b in pairs)
            if available
            else None,
        },
        "selection": {
            "rule": "all adjacent recorded-time pairs overlapping the closed interval",
            "sha256": digest([[str(a), str(b)] for a, b in pairs]),
        },
    }


def _event_observation(event: dict, provenance: dict | None) -> tuple[dict, dict]:
    event_id = event["event_id"]
    parameters = {
        "observed_value": event["observed_value"],
        "threshold": event["threshold"],
        "unit": event["unit"],
    }
    evidence = {
        "id": event_id,
        "kind": "detector_event",
        "event_id": event_id,
        "topic": event["topic"],
        "field": None,
        "unit": event["unit"],
        "clock": "recorded_receive",
        "start_timestamp_ns": event["start_timestamp_ns"],
        "end_timestamp_ns": event["end_timestamp_ns"],
        "availability": "available" if provenance else "partial",
        "reason": "Structured detector provenance" if provenance else "No structured provenance",
        "parameters": parameters,
    }
    text = (
        f"{event['event_type']} on {event['topic']}: "
        f"{event['observed_value']} {event['unit']}; "
        f"configured threshold {event['threshold']}."
    )
    if provenance:
        parameters.update(
            {
                k: v
                for k, v in provenance.items()
                if k not in {"samples", "matches", "boundary_samples"}
            }
        )
        sample_key = next(
            (k for k in ("samples", "matches", "boundary_samples") if k in provenance), None
        )
        if sample_key:
            evidence["selection"] = {
                **_selection(provenance[sample_key]),
                "artifact": "event_evidence.parquet",
                "event_id": event_id,
            }
        if provenance["kind"] == "image":
            evidence["field"] = provenance["field"]
            direction = "below" if provenance["comparator"] == "lt" else "above"
            text = (
                f"{provenance['sample_count']} analyzed frames on {event['topic']} had "
                f"{provenance['field']} {direction} {event['threshold']} {event['unit']}. "
                f"{provenance['finite_count']} of {provenance['analyzed_count']} analyzed frames "
                "in this detector interval had finite values."
            )
        elif provenance["kind"] == "gap":
            evidence["field"] = "inter_message_gap_ms"
            text = (
                f"{'Reference' if provenance['reference_context'] else 'Topic'} {event['topic']} "
                f"has a {event['observed_value']:.3f} ms recorded receive interval, "
                f"above the {event['threshold']:.3f} ms configured threshold."
            )
        elif provenance["kind"] == "motion":
            text = (
                f"{provenance['sample_count']} commands on {event['topic']} with linear speed "
                f">= {provenance['command_threshold_mps']} m/s matched "
                f"{provenance['odometry_topic']} "
                f"samples with speed <= {provenance['stationary_threshold_mps']} m/s. "
                f"Matching used the nearest recorded timestamp within "
                f"{int(provenance['matching_window_ns']) / 1e6:g} ms."
            )
            matches = provenance["matches"]
            parameters["minimum_offset_ms"] = min(int(m["offset_ns"]) for m in matches) / 1e6
            parameters["maximum_offset_ms"] = max(int(m["offset_ns"]) for m in matches) / 1e6
            for field in ("command_frame", "odometry_frame"):
                frames = sorted({m[field] or "" for m in matches})
                parameters[field + "s"] = frames[:20]
                parameters[field + "_count"] = len(frames)
    return (
        {
            "rule_id": event["event_type"],
            "text": text,
            "evidence_refs": [event_id],
            "parameters": parameters,
        },
        evidence,
    )


def validate_provenance(event: dict, provenance: dict | None) -> None:
    if provenance is None:
        return
    kind = provenance["kind"]
    key = {"image": "samples", "motion": "matches", "gap": "boundary_samples"}[kind]
    samples = provenance[key]
    if not samples or provenance["sample_count"] != len(samples):
        raise ValueError("Detector provenance sample counts do not reconcile")
    lo, hi = int(event["start_timestamp_ns"]), int(event["end_timestamp_ns"])
    if any(not lo <= int(s["timestamp_ns"]) <= hi for s in samples):
        raise ValueError("Detector evidence sample outside its event")
    if kind == "image":
        if not len(samples) <= provenance["finite_count"] <= provenance["analyzed_count"]:
            raise ValueError("Invalid image coverage counts")
        values = [s["value"] for s in samples]
        below = provenance["comparator"] == "lt"
        if (
            provenance["threshold"] != event["threshold"]
            or any(
                not math.isfinite(v)
                or not (v < event["threshold"] if below else v > event["threshold"])
                for v in values
            )
            or not math.isclose(
                min(values) if below else max(values),
                event["observed_value"],
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ):
            raise ValueError("Image evidence does not support its detector condition")
    elif kind == "motion":
        for sample in samples:
            offset = int(sample["odometry_timestamp_ns"]) - int(sample["timestamp_ns"])
            if (
                offset != int(sample["offset_ns"])
                or abs(offset) > int(provenance["matching_window_ns"])
                or sample["commanded_speed"] < provenance["command_threshold_mps"]
                or sample["observed_speed"] > provenance["stationary_threshold_mps"]
            ):
                raise ValueError("Motion match does not support its detector condition")
        if max(s["commanded_speed"] for s in samples) != event["observed_value"]:
            raise ValueError("Motion maximum does not reconcile")
    elif kind == "gap":
        if {int(s["timestamp_ns"]) for s in samples} != {lo, hi} or (hi - lo) / 1e6 != event[
            "observed_value"
        ]:
            raise ValueError("Gap boundaries do not reconcile")


def build_incidents(root: Path, directory: Path, metadata: dict, events: list[dict]) -> dict:
    rules = catalog(root)
    analysis = directory / metadata["analysis_path"]
    index = pl.read_parquet(analysis / "message_index.parquet")
    sidecar = pl.read_parquet(analysis / "anomaly_event_evidence.parquet")
    provenance_by_key = {r["event_key"]: json.loads(r["evidence_json"]) for r in sidecar.to_dicts()}
    normalized = normalize_events(events, metadata["source_sha256"])
    provenance = {}
    for event in normalized:
        provenance[event["event_id"]] = (
            _gap_evidence(event, index)
            if family(event) in {"recorded_gap", "reference_gap"}
            else provenance_by_key.get(event["event_key"])
        )
        validate_provenance(event, provenance[event["event_id"]])
    # Complete source evidence stays on disk. The API only exposes bounded examples.
    event_frame = (
        pl.DataFrame(
            normalized,
            schema_overrides={"start_timestamp_ns": pl.Utf8, "end_timestamp_ns": pl.Utf8},
            infer_schema_length=None,
        )
        if normalized
        else pl.DataFrame(
            schema={
                "event_id": pl.Utf8,
                "event_key": pl.Utf8,
                "start_timestamp_ns": pl.Utf8,
                "end_timestamp_ns": pl.Utf8,
                "start_s": pl.Float64,
                "end_s": pl.Float64,
                "topic": pl.Utf8,
                "event_type": pl.Utf8,
            }
        )
    )
    event_frame.write_parquet(directory / "events.parquet")
    pl.DataFrame(
        [
            {"event_id": key, "evidence_json": json.dumps(value, sort_keys=True)}
            for key, value in provenance.items()
        ],
        schema={"event_id": pl.Utf8, "evidence_json": pl.Utf8},
    ).write_parquet(directory / "event_evidence.parquet")
    domains = {
        name: pl.read_parquet(analysis / f"domain_records/{name}.parquet")
        for name in ("images", "odometry", "commands")
    }
    origin = int(metadata["origin_ns"])
    incidents = []
    for members in group_events(normalized, round(rules["max_group_span_s"] * 1e9)):
        kind = family(members[0])
        definition = rules["families"][kind]
        lo = min(int(e["start_timestamp_ns"]) for e in members)
        hi = max(int(e["end_timestamp_ns"]) for e in members)
        ids = sorted(e["event_id"] for e in members)
        observations, evidence = [], []
        limits = [definition["limits"]]
        hints = []
        for event in members:
            observation, ref = _event_observation(event, provenance[event["event_id"]])
            observations.append(observation)
            evidence.append(ref)
            if ref["field"]:
                hints.append({"topic": event["topic"], "field": ref["field"]})
        topic = members[0]["topic"]
        if kind == "image_content":
            delivery = _delivery(index, metadata, topic, lo, hi)
            evidence.append(delivery)
            if delivery["availability"] == "available":
                count = delivery["parameters"]["exceedance_count"]
                observations.append(
                    {
                        "rule_id": "delivery_context",
                        "text": (
                            "No recorded receive interval exceeded the configured threshold "
                            "in the inspected coverage."
                            if count == 0
                            else f"{count} recorded receive intervals exceeded the configured "
                            "threshold in the inspected coverage."
                        ),
                        "evidence_refs": [delivery["id"]],
                        "parameters": delivery["parameters"],
                    }
                )
                hints.append({"topic": topic, "field": "inter_message_gap_ms"})
            else:
                limits.append(delivery["reason"])
        motion = provenance[members[0]["event_id"]] if kind == "motion_disagreement" else None
        if motion and motion["odometry_topic_count"] > 1:
            limits.append(
                "Multiple odometry topics exist. The detector chose the topic with most "
                "records; robot association is ambiguous."
            )
        relevant_topics = {topic}
        if motion:
            relevant_topics.add(motion["odometry_topic"])
        for coverage in metadata["coverage"]:
            if coverage["topic"] in relevant_topics and coverage["extraction_error_count"]:
                limits.append(
                    f"{coverage['topic']}: {coverage['extraction_error_count']} extraction errors; "
                    "analyzed values do not cover every message."
                )
        for event in members:
            p = provenance[event["event_id"]]
            if p and p["kind"] == "image" and p["finite_count"] < p["analyzed_count"]:
                limits.append("Some analyzed image values are missing or non-finite.")
        # Navigable signal context is explicitly measured for this topic and interval.
        start_s, end_s = (lo - origin) / 1e9, (hi - origin) / 1e9
        padding = rules["context_padding_s"]
        display_start = max(0, start_s - padding)
        display_end = min(metadata["duration_s"], end_s + padding)
        checks = [
            {
                "text": definition["next_check"],
                "availability": "not_applicable",
                "reason": "Investigation guidance; additional inputs may need to be collected",
                "evidence_refs": [],
            }
        ]
        if motion:
            for domain, target in (("commands", topic), ("odometry", motion["odometry_topic"])):
                frame = domains[domain].filter(
                    (pl.col("topic") == target)
                    & pl.col("timestamp_ns").is_between(
                        origin + round(display_start * 1e9), origin + round(display_end * 1e9)
                    )
                )
                for field in ("linear_x", "angular_z"):
                    finite = frame.filter(pl.col(field).is_finite())
                    if not finite.height:
                        continue
                    ref_id = f"signal:{target}:{field}"
                    evidence.append(
                        {
                            "id": ref_id,
                            "kind": "signal",
                            "topic": target,
                            "field": field,
                            "unit": "rad/s" if field == "angular_z" else "m/s",
                            "clock": "recorded_receive",
                            "availability": "available",
                            "reason": "Recorded samples in the displayed context interval",
                            "start_timestamp_ns": str(origin + round(display_start * 1e9)),
                            "end_timestamp_ns": str(origin + round(display_end * 1e9)),
                            "parameters": {
                                "sample_count": finite.height,
                                "frames": sorted(
                                    set(
                                        finite[
                                            "child_frame_id" if domain == "odometry" else "frame_id"
                                        ]
                                        .fill_null("")
                                        .to_list()
                                    )
                                )[:20],
                                "frame_count": finite[
                                    "child_frame_id" if domain == "odometry" else "frame_id"
                                ].n_unique(),
                            },
                        }
                    )
                    hints.append({"topic": target, "field": field})
                    if field == "angular_z":
                        checks.append(
                            {
                                "text": f"Inspect angular motion on {target} "
                                "around the disagreement.",
                                "availability": "available",
                                "reason": "Angular velocity samples are present",
                                "evidence_refs": [ref_id],
                            }
                        )
        if kind == "image_content":
            for relation in metadata.get("relationships", []):
                if relation.get("source") != "configured" or topic not in {
                    relation.get("topic_a"),
                    relation.get("topic_b"),
                }:
                    continue
                other = relation["topic_b"] if relation["topic_a"] == topic else relation["topic_a"]
                frame = domains["images"].filter(
                    (pl.col("topic") == other)
                    & pl.col("timestamp_ns").is_between(lo, hi)
                    & pl.col("mean_intensity").is_finite()
                )
                if not frame.height:
                    continue
                ref_id = f"counterpart:{other}"
                if any(ref["id"] == ref_id for ref in evidence):
                    continue
                evidence.append(
                    {
                        "id": ref_id,
                        "kind": "related_context",
                        "topic": other,
                        "field": "mean_intensity",
                        "unit": "0–255",
                        "clock": "recorded_receive",
                        "availability": "available",
                        "reason": f"Configured relationship {relation['relationship_name']}; "
                        "samples overlap the incident; no shared cause inferred",
                        "start_timestamp_ns": str(lo),
                        "end_timestamp_ns": str(hi),
                        "parameters": {
                            "sample_count": frame.height,
                            "relationship": relation["relationship_name"],
                        },
                    }
                )
                checks.append(
                    {
                        "text": f"Compare recorded image intensity on {other}.",
                        "availability": "available",
                        "reason": "Configured counterpart",
                        "evidence_refs": [ref_id],
                    }
                )
        status = (
            "unsupported"
            if kind == "unsupported"
            else (
                "supported"
                if all(provenance[e["event_id"]] for e in members)
                else "insufficient_evidence"
            )
        )
        if status == "insufficient_evidence":
            limits.append(
                "Required structured detector provenance is unavailable; "
                "only the original warning is shown."
            )
        incident: Incident = {
            "incident_id": digest([GROUPING_VERSION, ids]),
            "family": kind,
            "title": definition["title"],
            "topics": sorted(relevant_topics),
            "start_timestamp_ns": str(lo),
            "end_timestamp_ns": str(hi),
            "start_s": start_s,
            "end_s": end_s,
            "member_event_ids": ids,
            "member_count": len(ids),
            "explanation_status": status,
            "severity": sorted({e["severity"] for e in members}),
            "grouping_reason": "Same-topic image warnings overlap the original seed; "
            "grouping does not establish cause."
            if len(members) > 1
            else "Original detector episode retained; no temporal-proximity merge.",
            "observations": observations,
            "evidence": evidence,
            "possibilities": [
                {"text": text, "status": "untested", "evidence_refs": []}
                for text in definition["possibilities"]
            ]
            if status == "supported"
            else [],
            "limits": list(dict.fromkeys(limits)),
            "next_checks": checks,
            "display_start_s": display_start,
            "display_end_s": display_end,
            "focus_s": max(0, min(start_s, metadata["duration_s"])),
            "plot_hints": list({(h["topic"], h["field"]): h for h in hints}.values()),
        }
        incidents.append(incident)
    document = {
        "schema_version": 1,
        "dataset_id": metadata["dataset_id"],
        "analysis_id": metadata["analysis_id"],
        "source_sha256": metadata["source_sha256"],
        "recipe_signature": metadata["recipe_signature"],
        "grouping_version": GROUPING_VERSION,
        "grouping_max_span_ns": str(round(rules["max_group_span_s"] * 1e9)),
        "catalog_version": rules["catalog_version"],
        "catalog_signature": digest(rules),
        "event_count": len(normalized),
        "incidents": incidents,
    }
    validate(document, normalized, metadata)
    return document


def validate(document: dict, events: list[dict], metadata: dict) -> None:
    for key in ("dataset_id", "analysis_id", "source_sha256", "recipe_signature"):
        if document.get(key) != metadata[key]:
            raise ValueError("Incident evidence identity mismatch")
    if document.get("schema_version") != 1 or document.get("grouping_version") != GROUPING_VERSION:
        raise ValueError("Unsupported incident schema or grouping version")
    by_id = {e["event_id"]: e for e in events}
    if len(by_id) != len(events) or document["event_count"] != len(events):
        raise ValueError("Incident event counts do not reconcile")
    expected_members = sorted(
        sorted(e["event_id"] for e in group)
        for group in group_events(events, int(document["grouping_max_span_ns"]))
    )
    actual_members = sorted(sorted(i["member_event_ids"]) for i in document["incidents"])
    if expected_members != actual_members:
        raise ValueError("Incident grouping does not match its recorded policy")
    seen = []
    for incident in document["incidents"]:
        ids = incident["member_event_ids"]
        if not ids or len(ids) != len(set(ids)) or incident["member_count"] != len(ids):
            raise ValueError("Invalid incident membership")
        if any(key not in by_id for key in ids):
            raise ValueError("Dangling incident member reference")
        if incident["incident_id"] != digest([GROUPING_VERSION, sorted(ids)]):
            raise ValueError("Invalid incident identity")
        if int(incident["start_timestamp_ns"]) != min(
            int(by_id[k]["start_timestamp_ns"]) for k in ids
        ) or int(incident["end_timestamp_ns"]) != max(
            int(by_id[k]["end_timestamp_ns"]) for k in ids
        ):
            raise ValueError("Invalid incident time bounds")
        refs = {r["id"] for r in incident["evidence"]}
        if len(refs) != len(incident["evidence"]):
            raise ValueError("Duplicate evidence reference")
        for observation in incident["observations"]:
            if not observation["evidence_refs"] or not set(observation["evidence_refs"]) <= refs:
                raise ValueError("Dangling observation evidence")
        for check in incident["next_checks"]:
            if not set(check["evidence_refs"]) <= refs:
                raise ValueError("Dangling next-check evidence")
        seen.extend(ids)
    if sorted(seen) != sorted(by_id):
        raise ValueError("Events lost or repeated in grouping")
    json.dumps(document, allow_nan=False)
