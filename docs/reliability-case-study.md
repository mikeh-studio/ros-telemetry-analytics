# Reliability case study

The project began as a one-robot recorded-replay observability system. This work
added a live ROS 2 gateway and tested what happens when telemetry becomes
incompatible, duplicated, delayed, disconnected, or interrupted by process loss.
This page is the single record of those results. Commands and pass criteria for
each experiment are in the [Live ROS 2 runbook](live-ros2.md); every number below
links to the saved result file that produced it.

## Localization detector study

A frozen environment split covers 21 published simulation runs. Fifteen runs
guide detector selection; six runs evaluate the selected candidate. Lowering the
particle-spread threshold from 0.40 m to 0.36 m improves held-out macro sample
recall from 36.2% to 45.5%, while precision falls from 92.4% to 85.7% and false
alarms increase. The default remains 0.40 m; the candidate is opt-in.

See [the study](../examples/localization_study.md) for per-run results and unmatched
events. Ground truth is used for scoring, never as detector input.

## Live integration and fault results

The gateway preserves ROS header time and coordinate frames while using reception
time for stream timing. A bounded SQLite outbox owns sequence numbers and retry
identities. A Nav2/Gazebo mission completed with about 0.98 m of odometry
displacement and 2,350 summarized gateway observations
([live_ros2_results.json](../examples/results/live_ros2_results.json)).

| Experiment | Result | What it shows | Evidence |
| --- | --- | --- | --- |
| Scan silence | 7 s silence; 1,356 publisher records and 1,403 gateway observations reconciled; one gap detected and recovered | Live gap detection with source-to-summary accounting | [live_ros2_results](../examples/results/live_ros2_results.json) |
| QoS mismatch and repair | Direct incompatibility callback; recovery visible 3.088 s after repair; 1,345 publications reconciled | Middleware evidence separates incompatible delivery from publisher silence | [qos_results](../examples/results/qos_results.json) |
| Duplicate transport | Ten duplicate deliveries; 1,637 unique observations counted once | Identity-based accounting | [transport_fault_results](../examples/results/transport_fault_results.json) |
| Delayed transport | Ten delayed events rejected with watermark evidence; 1,629 observations summarized | Watermark-based disposition | [transport_fault_results](../examples/results/transport_fault_results.json) |
| Gateway disconnect and SIGKILL | 500 buffered records survived SIGKILL; 1,781 accepted observations reconciled | Durable spool and stable retry IDs | [edge_recovery_results](../examples/results/edge_recovery_results.json) |
| Spool overflow | 1,378 observations summarized; 405 explicit rejections; all incidents recovered | Bounded storage with visible loss | [edge_recovery_results](../examples/results/edge_recovery_results.json) |
| Three simultaneous robots | 64.944 s overlap; both controls incident-free with 2,126 observations each | One robot's outage did not affect the other two | [fleet_isolation_results](../examples/results/fleet_isolation_results.json) |
| Projection API restart | 18 s outage; committed-data boundary reached in 1.158 s; 2,297 observations summarized | API projection catch-up | [projection_restart_results](../examples/results/projection_restart_results.json) |
| Flink worker restart | Checkpoint restored and a newer one completed in 46.898 s; 3,617 observations summarized; no unexpected incidents | Worker recovery with JobManager, Kafka and API running | [flink_restart_results](../examples/results/flink_restart_results.json) |
| Nav2 estimate disturbance | 2 m reset; 1,504 observations reconciled; one disagreement detected, then recovery | Post-run detection from live AMCL and odometry signals | [nav2_telemetry_results](../examples/results/nav2_telemetry_results.json), [nav2_localization_fault_results](../examples/results/nav2_localization_fault_results.json) |
| Incident signal sampling | 207 sampled observations match source attributes and retained API metrics | The incident view shows real source values | [signal_projection_results](../examples/results/signal_projection_results.json) |
| Trajectory projection | Coordinate frames preserved; positions grouped by topic and frame | Position plots never mix frames | [trajectory_projection_results](../examples/results/trajectory_projection_results.json) |
| Rendered incident view | Live QoS incident shown active, then recovered, in the browser | End-to-end UI behavior | [browser_review_results](../examples/results/browser_review_results.json) |

The unified suite runs ten of these cases in one command. Its first attempt failed
because one eligible odometry publication never reached the gateway, even though
every accepted message reconciled. The repeat passed with the same source gate.
Both attempts are kept in [reliability_suite_results](../examples/results/reliability_suite_results.json).

## Failures that changed the implementation

- Startup discovery produced misleading live rate alerts. Rate incidents now
  require a complete post-grace window.
- A one-second recovery gate required three messages from a 1 Hz topic. The gate
  now scales to the configured rate.
- Buffered recovery timestamps and projection ordering could leave an incident
  active. Recovery decisions preserve timing order, and newer anomaly revisions
  take precedence in the API.
- A delay experiment disproved the assumption that ten seconds of wall delay
  always means rejection: four events were accepted late and six rejected in
  development. Watermark evidence and counters now explain the difference.
- An API catch-up verifier wrongly required Kafka transaction-marker offsets as
  projected data offsets. The replacement freezes committed data-record boundaries.
- Flink checkpoint restoration produced a false robot-offline alert, and a fresh
  timer interval alone did not fix it. The watchdog now waits for source progress
  or accepted input and reports unknown health until observation resumes.
- One edge-recovery run immediately after a Flink rebuild missed the 60-second
  summary deadline (verified about 101 s after session end). It stays recorded as
  a failure.
- Per-record SQLite transactions made catch-up slow: a local 684-record fixture
  took 0.821 s, against 0.014 s with batched projection.

Every failed attempt is kept in its result file alongside the passing run.

## Evaluation rules

- Development cases may guide changes; final validation uses separate cases.
- Held-out localization scores are never used for tuning.
- Real DDS subscriptions, running Kafka/Flink and rendered UI checks are separate
  gates. Fixtures do not prove live integration.
- Transport faults and localization disturbance test different failure classes
  and keep separate ground truth.
- Received, queued, rejected, acknowledged, late, duplicate and projected counts
  are reconciled separately. A broker acknowledgment is not proof of detection.
- Detection delay, false alarms, recovery behavior and resource limits are reported.
- The original default is kept until evidence justifies replacing it.

## Coverage and remaining gaps

| Area | Covered | Not covered |
| --- | --- | --- |
| Localization evaluation | 21-run study with separate development and evaluation environments | Missed failures remain; recall is not solved |
| Live ROS 2 integration | Nav2/AMCL simulation through gateway, Kafka, Flink, API and Workbench; QoS failures observable | Physical robots |
| Fault suite | Silence, QoS, duplicates, delay, disconnection, overflow and localization disturbance in one command | Sustained delivery guarantees from repeated runs |
| Edge recovery | Single-gateway disconnection, hard restart and bounded overflow | Delivery of messages that never reached a stopped gateway |
| Multi-robot isolation | Three robots with an asymmetric outage and restart | Traffic spikes and capacity |
| Processing recovery | API hard restart and Flink worker checkpoint recovery | JobManager disaster recovery |

## Limits

These are small experiments on one local stack. They do not measure production
capacity or establish moving-robot localization accuracy. The localization
diagnostic assumes an initially consistent AMCL/odometry pair and bounded odometry
drift, and restoration was an explicit reset rather than autonomous relocalization.
Position plots show reported coordinates, not ground truth.

Raw experiment directories (publisher ledgers, captures, snapshots and failed
candidate reports) stay in ignored `data/evaluations/`; compact results are
checked into `examples/`.
