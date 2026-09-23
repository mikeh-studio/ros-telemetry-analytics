# Live ROS 2 gateway

Live single-robot integration has been exercised with headless Gazebo, Nav2 and
AMCL through Kafka, Flink, the API and rendered ROS Workbench. Reliability
experiments and their limits are tracked in [the roadmap](reliability-roadmap.md). This is simulation
integration evidence, not physical-robot or production-fleet validation.

## Runtime

The ROS 2 Jazzy gateway subscribes to the explicit profile in
[`configs/gateway.yaml`](../configs/gateway.yaml). It persists versioned envelopes
before Kafka delivery and uses the existing topic registration and terminal
lifecycle contracts. Scan, odometry, AMCL, and diagnostic inputs retain only
bounded scalar observations; raw scans and image payloads are not forwarded.

The source schema records `source_mode: live_ros2`. Gateway reception time drives
the existing arrival/rate checks; `attributes.ros_timestamp_ns` preserves the ROS
header timestamp separately. This does not measure hardware clock synchronization.
Reception timestamps do not regress within a process or on resume after a host
clock rollback. A source clock reset does not become an ingress clock reset.

The private health topic `/_telemetry/gateway_health` continues once per second
while sensor topics are silent. `/_telemetry/gateway_events` carries QoS evidence.
Health records distinguish an in-flight acknowledgment (`awaiting_ack`) from an
idle connected producer and include its wait duration. Last acknowledgment time
is process-local and starts unset after restart; durable acknowledgment counters
continue from the spool.
Missing sensor data while the gateway is active differs from missing evidence
from the gateway itself; neither alone establishes the physical root cause.

Gateway entry point for an existing reachable ROS publisher:

```bash
docker compose -f compose.yaml -f compose.live.yaml up --build
```

The profile uses ROS domain 42 by default. A simulator or robot publisher must
share the domain and a reachable DDS network. The gateway defaults to best-effort
subscriptions, compatible with sensor publishers; topics can request reliable
QoS explicitly. Incompatible QoS callbacks become gateway event records.

## Bundled navigation experiment

```bash
docker compose -f compose.yaml -f compose.live.yaml -f compose.simulation.yaml \
  --profile mission up --build
```

This uses the official Nav2 Jazzy Gazebo sandbox, with AMCL initialized at its
known spawn pose before the navigation lifecycle activates. The mission runner
waits for active Nav2, sends a one-meter goal, and records action status and
odometry under `data/evaluations/nav2/mission.json`. It is a simulator-only
runner. The gateway uses the installed model's 5 Hz scan and 30 Hz odometry
targets; AMCL pose is movement-driven and has rate monitoring disabled.

The default gateway session is two minutes. A reused closed gateway volume only
drains its previous session. To start another session after it has fully drained:

```bash
docker compose -f compose.yaml -f compose.live.yaml -f compose.simulation.yaml \
  run --rm gateway python3 -m demo.gateway.ros_node \
  --config configs/gateway_nav2.yaml --new-session
```

The simulator is based on the [official Nav2 quickstart](https://docs.nav2.org/jazzy/getting_started/quickstart/quickstart/).
Package versions and image IDs should be recorded for each evaluation; ROS apt
packages are not frozen by the base-image digest alone.

## Recovery and limits

- Every accepted observation, sequence allocation, and queue update is committed
  in one SQLite transaction. An uncertain send retains the exact persisted
  envelope for retry. This is at-least-once transport with stable IDs.
- Only a broker acknowledgment removes the head. The Kafka/Flink downstream
  deduplication and late-event behavior must be evaluated separately.
- Default pending payload budget is 8 MB and 10,000 records, with an additional
  64 KiB/32-record control reserve so a full data queue can still close its run.
  New observations beyond the data budget are rejected and counted; their
  sequence numbers remain gaps. Old pending evidence is not evicted.
- SQLite allocation has a separate 32 MB database ceiling. DELETE journaling
  prevents an indefinitely growing WAL; provision at least 96 MB for the DB,
  rollback journal, and filesystem overhead. This is a spool budget, not a bound
  on container logs or ROS middleware memory. Filesystem I/O errors stop ingestion;
  they are not silently converted to successful delivery.
- Sessions are bounded to one hour maximum; the example lasts two minutes.
  On graceful shutdown, terminal envelopes and watermark flush records are
  appended after queued telemetry. The gateway tries to drain for 30 seconds.
  Watermark flush records wait until their timestamp is reached in wall time;
  a closing run must not advance another live run into the future.
  Exit code 2 means pending evidence remains durable and needs delivery later.
- Restarting with the same outbox resumes its identity and pending records. A
  closed outbox only drains. `--new-session` allocates a new identity only after
  the previous session is closed and fully acknowledged.
- Run ROS 2 with its sourced environment, or use the image's ROS entry point.
  The gateway opens no robot command interface.

Broker outages longer than the Flink allowed-lateness interval may route
recovered observations to late evidence instead of revising past alerts. Broker
delivery alone must not be reported as full analytical recovery. Concurrent live
streams and accelerated replay also require explicit event-time validation.

## Local verification

```bash
.venv/bin/python -m pytest tests/demo/test_gateway.py -q
```

The tests cover uncertain acknowledgment and identical retry, abrupt process
exit, session resume, overflow counters and sequence gaps, reserved control
capacity, source/receive clock separation, schema-valid lifecycle envelopes, and
exclusive ownership of an outbox.

## Repeatable transport evaluation

With the local stack healthy, run:

```bash
docker build -f demo/gateway/Dockerfile -t ros-telemetry-gateway:development .
.venv/bin/python scripts/run_gateway_eval.py \
  --output data/evaluations/gateway-validation-new
```

The output directory must be new. The script records an image ID, independent
publisher ledger, durable gateway counters, bounded read-committed Kafka offset
snapshot, API summary verification, and evaluation JSON. Its default 45-second
run injects scan silence from seconds 12 to 19. This is a real DDS message
fixture, separate from navigation. It does not test broker outages or physical
sensor failures.

Evaluation distinguishes event-time detection from broker-visible detection and
recovery. Source reconciliation includes discovered subscribers within the
session, excluding the final 100 ms teardown boundary; excluded publications are
reported explicitly. A pass requires detection, recovery, no unexpected alerts,
no duplicate envelopes or late/schema rejections, and verified summary counts.

Live rate alerts require a complete window after startup grace. Windows containing
DDS discovery remain visible but cannot open a rate incident. Later low rates
still trigger the detector. ROS Workbench disables replay controls for live runs,
shows actual robot identity, and isolates completion warnings by run. The API
retains eight recent runs and 100 incident transitions per run; this is a bounded
demo retention policy, not an archival fleet service.

## QoS incompatibility and repair

```bash
.venv/bin/python scripts/run_gateway_eval.py \
  --output data/evaluations/qos-new --fault qos --domain 48 \
  --duration-s 50 --dropout-end-s 24
```

This case starts a reliable scan subscriber against a best-effort publisher.
The publisher continues sending, then recreates its scan publisher as reliable
at second 24. For this case, `--dropout-end-s` sets the repair time; there is no
intentional publication silence. The mismatch starts at startup, so the expected
health incident is `NEVER_SEEN` rather than a gap after previous observations.

A pass requires a direct ROS QoS incompatibility callback, independent evidence
of ongoing publication, no scan delivery during incompatibility, recovery after
repair, an empty projected active-incident list, and reconciled summary counts.
Discovery and teardown exclusions remain explicit. This validates DDS transport
and monitoring behavior; it does not diagnose a physical sensor failure.

## Duplicate and delayed transport

```bash
.venv/bin/python scripts/run_gateway_eval.py \
  --output data/evaluations/duplicate-new --fault duplicate --domain 53 \
  --duration-s 50 --dropout-start-s 16 --dropout-end-s 24
.venv/bin/python scripts/run_gateway_eval.py \
  --output data/evaluations/delay-new --fault delay --domain 54 \
  --duration-s 50 --dropout-start-s 16 --dropout-end-s 24
```

Both cases continue real DDS publication. A test-only transport shim targets the
first ten scan envelopes after second 16. Duplicate mode sends each envelope
twice with its original identity. Delay mode hands selected envelopes to an
in-memory delay task and sends them ten seconds later while other traffic
continues. This deliberately bypasses the normal gateway acknowledgment contract;
it tests downstream handling, not spool durability or crash recovery.

The independent injection ledger records identities and actual handoff/completion
times. The evaluator reconciles eligible DDS publications, Kafka multiplicity,
disposition IDs, summary counters, and accepted observation totals. Delay is
measured against wall time; lateness acceptance depends on Flink's watermark.
Accepted-late and rejected counts can therefore vary between runs. Rejections
must carry watermark evidence beyond the five-second allowance, and every
injected delayed identity must appear in sequence-regression evidence. Sequence
gaps/regressions are diagnostics, not additional rejected observations.

## Incident signals and sampled positions

For incident signal verification, run the QoS case above and then:

```bash
.venv/bin/python scripts/evaluate_signal_projection.py \
  --capture data/evaluations/qos-new/kafka.json \
  --snapshot data/evaluations/qos-new/snapshot.json \
  --output data/evaluations/qos-new/signals.json
```

Flink emits `observed_signal` metrics only for accepted live observations, sampled
once per second per topic. The API retains 180 samples per robot/topic. The
evaluator compares source fields and attributes, topic sampling, the retained API
set, and QoS evidence. These are sampled observations, not a complete trajectory
or proof of localization correctness. ROS header time remains in attributes;
stream timing uses gateway reception time.

The incident position view groups samples by topic and reported ROS coordinate
frame. AMCL and odometry are not overlaid or transformed. Plots use equal X/Y
scale and show dots without interpolating missing observations; the incident
interval is highlighted. Samples without a finite position or declared frame are
excluded. The gateway preserves frame identifiers up to 512 characters and leaves
longer identifiers unknown rather than truncating distinct frames into one name.
These plots show reported motion only, not localization error or ground truth.

## Controlled Nav2 localization disturbance

```bash
.venv/bin/python scripts/run_nav2_localization_eval.py \
  --output data/evaluations/nav2-localization-new --domain 74 --offset-m 2.0 \
  --with-telemetry
```

This command creates its own Gazebo/Nav2 containers and records baseline,
disturbance, and repair actions. It shifts AMCL's initial-pose estimate while
sending no navigation goal, then explicitly resets the estimate to the bundled
world's known spawn pose. Timestamped AMCL and odometry observations establish
whether the estimate changed, whether it returned, and whether odometry moved.
Owned containers are stopped and their logs retained afterward.

With `--with-telemetry`, the command also starts an owned gateway, captures Kafka
and API evidence, and writes `telemetry-evaluation.json`. All eleven gates must
pass, including source preservation, verified summaries, a detected disagreement,
and recovery after repair. Without this option it evaluates only fault generation.

The post-run diagnostic compares AMCL displacement with odometry displacement,
using the initial paired orientations to align their frames. It receives no spawn
reference or injection labels. It assumes the first pair is consistent and odometry
drift remains bounded; missing recent causal odometry or changed frames produces
unknown evidence. The stationary 1.5 m and independent 2 m runs pass. Restoration
is an explicit reset, not autonomous relocalization. This diagnostic is not wired
into production stream alerts and has not been evaluated on moving real robots.
Reported detection offsets use reception timestamps, not post-run execution time.

The [retained localization fault results](../examples/nav2_localization_fault_results.json)
record the development and evaluation runs for this controlled disturbance.

## Unified reliability suite

```bash
.venv/bin/python scripts/run_reliability_suite.py \
  --output data/evaluations/reliability-suite-new --keep-going
```

Run against the existing local Compose stack. The command sequentially evaluates
silence, QoS, duplicates, delay, edge recovery, overflow, three-robot isolation,
API restart, Flink worker restart, and localization telemetry. It intentionally
restarts the local API and TaskManager in their respective cases. Each case keeps
its raw evidence and log; the root `evaluation.json` passes only if every requested
case exits successfully and its evaluation passes. Omit `--keep-going` to stop at
the first failure, or select cases with `--cases`. Use a new output directory each
time. This command does not perform the separate rendered browser review.

## Flink worker checkpoint recovery

```bash
.venv/bin/python scripts/run_flink_restart_eval.py \
  --output data/evaluations/flink-restart-new --duration-s 100 \
  --warmup-s 18 --outage-s 12 --domain 68
```

The test requires a completed checkpoint from the active DDS run, then hard-stops
the TaskManager while the JobManager, Kafka, and API stay running. After restart,
the same job must report an increased restore count, a restored checkpoint at
least as recent as the captured one, and a newer completed checkpoint within
60 seconds. The source evaluation separately checks summaries, duplicates,
lateness, and incidents. A running process alone cannot satisfy the recovery gate.
The script restores the worker on failure. This does not test JobManager loss.

Restored processing timers cannot establish robot silence while the observer was
stopped. A restored watchdog waits for accepted input or source-watermark progress
before starting a fresh observation interval. Health is unknown while observation
is unavailable, and aggregate health preserves that distinction. Once observation
resumes, normal silence detection remains enabled. This prevents the false offline
incident found in the first two recovery experiments.

## Projection restart and catch-up

```bash
.venv/bin/python scripts/run_projection_restart_eval.py \
  --output data/evaluations/projection-restart-new --duration-s 70 \
  --warmup-s 16 --outage-s 18 --domain 66
```

This experiment hard-stops the local projection API while DDS, Kafka, and Flink
continue. It restores the same container and SQLite volume, then checks recovery
against a frozen boundary of committed Kafka data records within 30 seconds.
Transaction markers are excluded: SQLite offsets describe projected records, so
an idle partition may legitimately stay below the broker log end. The evaluator
also requires accumulated backlog, an unchanged run identity, a passing source
evaluation, and verified final summaries. It restores the API on failure.

This tests API catch-up; it does not substitute for a Flink checkpoint-recovery
experiment or claim production throughput.

## Three concurrent robots

```bash
.venv/bin/python scripts/run_fleet_isolation_eval.py \
  --output data/evaluations/fleet-new --duration-s 65 \
  --warmup-s 16 --outage-s 17 --domain-base 62
```

This command runs two clean DDS controls and a third gateway with network
disconnection and SIGKILL/restart. All three share Kafka, Flink, and the API;
separate DDS domains or bridges isolate their sensor publishers. Each child
retains its own source ledger, capture, and evaluation. The parent checks actual
run overlap, distinct identities, clean control incidents, and the faulted run's
recovery. It re-fetches all three API snapshots after every run completes, so
earlier per-run success cannot hide a later retention or identity regression.

This is a small local isolation experiment with one asymmetric outage. It does
not measure production fleet capacity or guarantee delivery of sensor messages
that never reached the gateway while it was stopped.

## Gateway disconnection, restart, and overflow

```bash
.venv/bin/python scripts/run_edge_recovery_eval.py \
  --output data/evaluations/edge-recovery-new --warmup-s 10 --outage-s 15 --duration-s 55
.venv/bin/python scripts/run_edge_recovery_eval.py \
  --output data/evaluations/edge-overflow-new --warmup-s 10 --outage-s 15 --duration-s 55 \
  --max-pending-records 96 --expect-overflow
```

Each experiment creates its own DDS bridge, disconnects only its gateway from
the existing Kafka network, verifies that sensor observations accumulate without
acknowledgment progress, sends SIGKILL, and restarts the same spool with Kafka
connectivity restored. The shared broker and stream processors remain running.
Owned test containers are stopped afterward; their logs and consistent SQLite
snapshots are retained. The temporary DDS network is removed.

Checks compare complete persisted envelope contents as JSON values with broker
records, reconcile received/acknowledged/rejected counts and sequence gaps, and
verify analytical summaries separately. Publisher observations absent from the
gateway are reported, not treated as recovered. No disk queue can recover an
observation that never reached the gateway during downtime.

The `telemetry.late.v1` stream also carries sequence-gap and duplicate diagnostics.
The evaluator classifies these explicitly: a sequence-gap diagnostic is evidence
of omitted sequence numbers, not an additional rejected observation. Unknown
dispositions fail evaluation. Overflow can therefore be a successful accounting
test while still representing real rejected data and downstream health incidents.

Slow monitored topics use a recovery window long enough to observe at least
three messages at their configured rate (three seconds at 1 Hz). Fast sensors
retain the existing one-second density gate. This avoids a permanent gap state
that would otherwise demand an impossible three-message burst from a 1 Hz topic.

Anomaly revisions take precedence over event timestamps in the projection. A
newer recovery revision cannot be hidden by an older active revision. The
processing-time robot watchdog maps elapsed recovery time onto the stream clock
and records the original buffered observation time separately; recovery must
not appear to predate its offline decision. End-to-end evaluation checks the
projected active-incident list as well as raw recovered transitions.

The API projects up to 500 Kafka records and their offsets in one SQLite
transaction, then commits consumer offsets once per batch. A failed SQLite batch
rolls back both data and offsets. Recovery seeks the stored SQLite offsets, so
a crash between SQLite and Kafka offset acknowledgment does not lose projected
records. This also reduces the per-record transaction overhead exposed by
post-rebuild catch-up evaluation.

## Watchdog clock and startup-window interpretation

Topic-window timestamps use stream time. Robot-wide watchdog decisions use a
processing-time observation interval projected onto the stream clock. During
buffered recovery, the decision timestamp is the later of the accepted event's
stream time and the offline start plus elapsed processing time. The original
accepted timestamp remains in `evidence.recovery_observation_stream_ms`; the
`decision_clock` field identifies this policy.

This is not a globally monotonic event-time sequence across topic metrics,
watchdog metrics, checkpoints, and runs. A restored active watchdog retains its
processing-time anchor; process downtime may therefore contribute to its elapsed
decision time. Consumers must group by run and robot, order anomaly revisions by
revision, and must not interpret projected recovery time as a ROS acquisition
time or measured transport latency. The API uses revision precedence for anomaly
state. Replacing these decision timestamps with buffered event timestamps would
reintroduce recoveries preceding their offline decision.

Live windows overlapping discovery grace expose
`payload.rate_evaluation_status: startup_grace` and report `health_status: starting`
when rate monitoring is enabled and no active condition takes precedence. Other values distinguish
`event_driven`, `partial_window`, `structural_suppression`, and `normal_window`.
Normal windows still pass the existing lifecycle and recovery gates before rate
alerts can change. The marker does not assert that a publisher is configured
correctly: missing topics can raise NEVER_SEEN after their deadline, and a
persistently incorrect rate is evaluated after the full post-grace window.
