"""Causal relative-motion check for short, initially consistent paired pose streams.

No map truth or injection labels enter the detector. This is a diagnostic for
AMCL/odometry disagreement, not proof that either estimate is correct.
"""

import math


def evaluate_consistency(signals, threshold_m=0.5, max_pair_age_ms=1500):
    anchor = None
    odometry = []
    states = []
    transitions = []
    active = False
    for signal in sorted(signals, key=lambda row: row["stream_timestamp_ms"]):
        attrs = signal.get("payload", {}).get("attributes", {})
        if signal["topic"] not in {"/odom", "/amcl_pose"}:
            continue
        valid = attrs.get("frame_id") and all(
            isinstance(attrs.get(key), (float, int)) and math.isfinite(attrs[key])
            for key in ("position_x", "position_y", "yaw", "ros_timestamp_ns")
        )
        if not valid:
            continue
        if signal["topic"] == "/odom":
            odometry.append(signal)
            odometry = odometry[-10:]
            continue
        candidates = [
            row
            for row in odometry
            if 0
            <= attrs["ros_timestamp_ns"] - row["payload"]["attributes"]["ros_timestamp_ns"]
            <= max_pair_age_ms * 1_000_000
            and row["run_id"] == signal["run_id"]
            and row["robot_id"] == signal["robot_id"]
        ]
        if not candidates:
            states.append(
                {
                    "stream_timestamp_ms": signal["stream_timestamp_ms"],
                    "state": "unknown",
                    "reason": "no_recent_causal_odometry",
                }
            )
            continue
        odom = max(candidates, key=lambda row: row["payload"]["attributes"]["ros_timestamp_ns"])[
            "payload"
        ]["attributes"]
        identity = (signal["run_id"], signal["robot_id"], attrs["frame_id"], odom["frame_id"])
        if anchor is None:
            anchor = (identity, attrs, odom)
        if identity != anchor[0]:
            states.append(
                {
                    "stream_timestamp_ms": signal["stream_timestamp_ms"],
                    "state": "unknown",
                    "reason": "reference_identity_or_frame_changed",
                }
            )
            continue
        _, initial, initial_odom = anchor
        angle = initial["yaw"] - initial_odom["yaw"]
        dx, dy = (
            odom["position_x"] - initial_odom["position_x"],
            odom["position_y"] - initial_odom["position_y"],
        )
        predicted_x = initial["position_x"] + math.cos(angle) * dx - math.sin(angle) * dy
        predicted_y = initial["position_y"] + math.sin(angle) * dx + math.cos(angle) * dy
        residual = math.hypot(attrs["position_x"] - predicted_x, attrs["position_y"] - predicted_y)
        inconsistent = residual > threshold_m
        state = {
            "stream_timestamp_ms": signal["stream_timestamp_ms"],
            "state": "inconsistent" if inconsistent else "consistent",
            "residual_m": residual,
            "threshold_m": threshold_m,
            "paired_odometry_age_ms": (attrs["ros_timestamp_ns"] - odom["ros_timestamp_ns"])
            / 1_000_000,
        }
        states.append(state)
        if inconsistent != active:
            transitions.append({**state, "status": "active" if inconsistent else "recovered"})
            active = inconsistent
    return {
        "states": states,
        "transitions": transitions,
        "active": active,
        "scope": (
            "Relative-motion disagreement since first paired sample; "
            "assumes initial consistency and bounded odometry drift"
        ),
    }
