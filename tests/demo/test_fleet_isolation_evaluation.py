from copy import deepcopy

from scripts.run_fleet_isolation_eval import isolation_checks


def cases():
    result = {}
    for name in ("control_a", "control_b", "fault"):
        identity = {"run_id": name, "robot_id": "robot-" + name}
        result[name] = {
            "snapshot": {
                **identity,
                "topics": [],
                "anomalies": [],
                "completion": {"verified": True},
                "mission_summaries": {},
            },
            "evaluation": {
                "passed": True,
                "crash_wall_ms": 20000,
                "restart_wall_ms": 22000,
                "incident_transitions": [{"status": "active"}, {"status": "recovered"}],
            },
            "capture": {
                "records": {
                    "telemetry.events.v1": [
                        {
                            "value": {
                                **identity,
                                "envelope_type": "run_started",
                                "stream_timestamp_ms": 0,
                            }
                        },
                        {
                            "value": {
                                **identity,
                                "envelope_type": "run_ended",
                                "stream_timestamp_ms": 60000,
                            }
                        },
                    ],
                    "telemetry.metrics.v1": [],
                    "telemetry.anomalies.v1": [],
                }
            },
        }
    return result


def test_isolation_rejects_cross_robot_projection_and_nonoverlapping_runs():
    evidence = cases()
    assert isolation_checks(evidence)["passed"]
    bad = deepcopy(evidence)
    bad["control_a"]["snapshot"]["topics"] = [{"run_id": "control_a", "robot_id": "robot-fault"}]
    assert not isolation_checks(bad)["checks"]["identities_isolated"]
    bad = deepcopy(evidence)
    bad["control_a"]["capture"]["records"]["telemetry.events.v1"][0]["value"][
        "stream_timestamp_ms"
    ] = 50000
    assert not isolation_checks(bad)["checks"]["concurrent_for_thirty_seconds"]
    assert not isolation_checks(bad)["checks"]["restart_during_shared_interval"]


def test_isolation_requires_clean_controls_and_retained_verified_outputs():
    evidence = cases()
    evidence["control_a"]["snapshot"]["anomalies"] = [
        {"run_id": "control_a", "robot_id": "robot-control_a"}
    ]
    assert not isolation_checks(evidence)["checks"]["controls_have_no_incidents"]
    evidence["control_b"]["snapshot"]["completion"]["verified"] = False
    assert not isolation_checks(evidence)["checks"]["all_runs_still_retained_and_verified"]
