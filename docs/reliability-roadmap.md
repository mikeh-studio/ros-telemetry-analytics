# Reliability improvement work

Objective: build out the remaining robotics reliability improvements and use
evaluation evidence to guide implementation. This document tracks completion
against the requested end state, including runtime validation.

| Requirement | Evidence required | Current state |
| --- | --- | --- |
| Localization evaluation | Separate development/evaluation environments, reproducible diagnostics and tradeoffs | Implemented; 21-run study, opt-in 0.36 m candidate; missed failures remain |
| Live ROS 2 integration | Running Nav2/AMCL simulation sends selected topics through gateway, Kafka, Flink, API and ROS Workbench; source and receive clocks distinguished; QoS failures observable | Navigation path runtime-validated; separate DDS QoS mismatch/repair validation passes |
| Repeatable fault suite | One command injects sensor silence, delay, duplicates, gateway disconnection, and localization disturbance; validates detection/recovery against independent expectations | Unified command implemented; complete ten-case runtime validation passes; initial failed attempt retained |
| Edge recovery | Durable bounded spool; stable retry IDs; broker outage and gateway restart; explicit overflow; source-to-sink reconciliation | Single-gateway disconnection, hard restart and bounded overflow validated; broader isolation remains separate |
| Incident explanation | One-screen evidence for affected topics, timeline, available localization/trajectory signals and recovery; observations distinct from suspected causes | Grouped view, sampled signals and frame-separated trajectories validated in the browser during a live QoS incident and recovery |
| Case study | Repeatable before/fault/recovery experiment with actual runtime results and limitations | Implemented with linked runtime results, failed experiments, changes, and explicit limits |
| Multiple-stream isolation | Three concurrent robot streams; one outage or traffic spike cannot corrupt another robot's state | Three-robot asymmetric outage/restart validated; not a traffic-spike or capacity benchmark |
| Processing recovery | Repeatable restart and bounded catch-up with source and summary reconciliation | API hard restart and Flink worker checkpoint recovery validated; JobManager disaster recovery is outside this experiment |

The stationary Nav2/Gazebo disturbance now travels through the live gateway,
Kafka, Flink, and API. A separate post-run relative-motion diagnostic consumes only
projected AMCL and odometry signals; reset actions are used afterward for scoring.
Development (1.5 m) and independent validation (2 m) pass all eleven checks. The
validation reconciles 1,504 observations, identifies one disagreement interval,
and observes recovery after explicit restoration. Its 110 ms onset and 134 ms
recovery offsets use gateway reception time, not diagnostic execution latency.
This assumes an initially consistent pose pair and bounded odometry drift; moving
robots, autonomous relocalization, and production stream alerting remain unproven.
It does not establish improved recall on the separate TUHH study. See
[`examples/nav2_telemetry_results.json`](../examples/nav2_telemetry_results.json).
Current verification passes 235 Python tests, 18 frontend tests, lint, diff checks,
and the frontend production build. Rendered review now passes for the live QoS scenario.

The unified suite retains every case result and requires both successful process
exit and passing evaluation evidence. Its first run stopped on one missing
eligible odometry publication, well inside the session, despite complete accounting
of all 1,402 accepted gateway observations. That failed run remains retained;
accepted-to-summary reconciliation does not establish publisher-to-gateway delivery.
A subsequent complete run passes all ten cases without relaxing the source gate:
silence, QoS, duplicates, delay, edge recovery, overflow, three-stream isolation,
API restart, Flink worker restart, and Nav2 localization telemetry. Both attempts
are preserved in [`examples/reliability_suite_results.json`](../examples/reliability_suite_results.json).
One successful complete run does not establish a sustained delivery guarantee.
The final rendered incident-view gate was completed after explicit browser approval.
A fresh QoS run passes all fourteen runtime checks and reconciles 1,396 gateway
observations. Browser inspection verified active-to-recovered state, preserved
timeline, direct QoS evidence, and frame-separated position plots. It exposed
rounded nanosecond values in JavaScript; these now carry an approximate label,
verified after rebuilding the web container. See
[`examples/browser_review_results.json`](../examples/browser_review_results.json).
This completes the scoped improvement work, with the experiment limits retained;
it does not establish production-fleet reliability or solve localization recall.

Runtime results and discovered regressions are recorded in
[`examples/live_ros2_results.json`](../examples/live_ros2_results.json).
The final transport case reconciles 1,356 eligible publisher records and all
1,403 gateway observations with verified summaries. A seven-second scan silence
produces one detected/recovered gap and no unexpected alerts. The separate Nav2
mission succeeds with about 0.98 m of odometry displacement and 2,350 gateway
observations, five verified summaries, and no late/schema/anomaly records.
These checks do not complete the remaining rows above.

The separate QoS validation keeps publishing scans while reliability settings are
incompatible, records the direct middleware callback, then repairs the publisher.
All 14 checks pass: 1,345 eligible publications reconcile, 1,399 gateway
observations are summarized, and the projected incident list recovers completely.
The broker-visible recovery arrives 3.088 seconds after repair. Another 255
publications are explicitly excluded by discovery/teardown eligibility rules.
See [`examples/qos_results.json`](../examples/qos_results.json) for both development
and independent timing validation. This is a DDS fixture, not a physical failure.

The edge recovery validation preserved 500 buffered records through SIGKILL and
reconciled all 1,781 accepted observations with summaries. An overflow experiment
exposed an impossible recovery gate for 1 Hz health topics; the corrected gate
recovers the actual stream. One run immediately after a Flink rebuild exceeded
the 60-second summary deadline (eventual verification about 101 seconds after
session end). Keep this failure visible; broker delivery and eventual completion
do not prove timely projection after processing-service restart.

The stronger overflow validation now passes 21 checks: 1,378 accepted observations
are delivered and summarized, 405 rejections remain explicit, sequence gaps
reconcile, every incident recovers, and the projected active list is empty.
See [`examples/edge_recovery_results.json`](../examples/edge_recovery_results.json)
for the original failed candidates and final results. Fixes include slow-topic
recovery, anomaly revision ordering, monotonic watchdog recovery decisions, and
atomic projection batches. A controlled local 684-record projection fixture took
0.821 seconds with per-record transactions and 0.014 seconds with batches; this
is not a production throughput claim. Repeatable processing-service restart
catch-up and Flink worker checkpoint recovery validation are described below.

## Evaluation rules

Two Flink worker restart experiments restored checkpoints within 47 seconds and
reconciled source observations and summaries, but both raised an unexpected
robot-offline incident. A fresh timer interval alone did not solve delayed source
startup. The current repair keeps a restored watchdog unknown until accepted
input or source-watermark progress re-establishes observation, then resumes the
normal silence policy; aggregate health preserves that unknown state. Flink build
verification and checkpoint harness tests pass. Final runtime validation passes
all six checks: restoration and a newer checkpoint in 46.898 seconds, 3,617
observations reconciled, and no unexpected incidents. Failed results remain in
[`examples/flink_restart_results.json`](../examples/flink_restart_results.json).
The [case study](reliability-case-study.md) records the broader findings and limits.

The API restart validation hard-stops the projection process for 18 seconds while
the source and Flink continue. It reaches a frozen committed-data boundary in
1.158 seconds, covering 356 log-offset positions, then verifies all 2,297 accepted
observations in the final summaries. All seven restart checks pass. The initial
verifier's failed result is preserved: broker transaction-marker offsets cannot
be required as SQLite data-record offsets. The corrected probe excludes those
markers and is tested with idle partitions and records beyond the frozen boundary.
See [`examples/projection_restart_results.json`](../examples/projection_restart_results.json).
This verifies API recovery only; it does not establish Flink checkpoint recovery.

The three-robot isolation command passes both development and later-outage
validation. The final runs overlap for 64.944 seconds. Both clean controls retain
2,126 summarized observations with no incidents; the faulted robot recovers and
summarizes 1,687 accepted observations. The parent re-reads every run after all
children complete and checks identities across metrics, incident history,
signals, summaries, and robot health. All nine isolation checks pass, alongside
each child's source/recovery evaluation. Results and exclusions are retained in
[`examples/fleet_isolation_results.json`](../examples/fleet_isolation_results.json).
This is one asymmetric gateway outage and hard restart on a local stack, not a
production fleet capacity result. 

Duplicate and delay cases now use a test-only shim between DDS reception and
Kafka. Independent timing validation counts 1,637 unique observations once despite
ten duplicate deliveries. The delay case reconciles 1,629 accepted observations
and ten rejected events, each with watermark evidence. Both cases have no
unexpected incidents. The original delay evaluator incorrectly assumed that wall
delay guarantees rejection; its failed report is preserved alongside the corrected
watermark/counter evaluation (four accepted late, six rejected in development).
See [`examples/transport_fault_results.json`](../examples/transport_fault_results.json).
The shim's in-memory handoff is explicitly not a spool durability guarantee.


The incident view groups revisions by run and anomaly identity, selects the latest
revision even when timestamps arrive out of order, and shows opening/recovery
timestamps with detector evidence. Pruned opening history is explicitly unknown.
Cause remains unconfirmed, and the separate public localization recording is not
used as evidence for a live incident. The new `observed_signal` metric carries the
first accepted live observation per second for each topic. Duplicate and rejected
events do not enter that path. API retention keeps 180 samples per robot/topic
within its eight-run policy. The incident view filters by run, robot, and the
interval from five seconds before onset to five seconds after recovery; available
attributes are labeled as observations, not inferred causes. Flink verification
and the end-to-end QoS run pass. All 207 sampled observations reconcile exactly
with source attributes and retained API metrics, including AMCL pose, odometry,
and the direct QoS callback. The validator rejects missing projected samples and
altered source attributes. See
[`examples/signal_projection_results.json`](../examples/signal_projection_results.json).
Rendered verification initially required explicit browser approval; the completed review is recorded above.

The trajectory component excludes missing/nonfinite positions and unknown frames,
groups each robot/topic/frame separately, and uses equal X/Y scale without
interpolating gaps. A fresh DDS run passes all 14 transport checks and the signal
evaluator now checks coordinate-frame preservation as well. Results are in
[`examples/trajectory_projection_results.json`](../examples/trajectory_projection_results.json).
Component tests and source reconciliation support data behavior. The separate
rendered review verified these plots in the default app panel viewport.

- Development cases may guide changes; preserve separate final validation cases.
- Do not tune on held-out localization candidate scores and call them untouched.
- Real DDS subscriptions, running Kafka/Flink, and rendered UI evidence are
  separate gates. Fixtures do not prove live integration.
- Transport fault injection and localization disturbance test different failure
  classes. Keep their ground truth and assertions distinct.
- Reconcile received, durably queued, rejected, acknowledged, late, duplicate,
  and projected evidence. A broker acknowledgment is not proof of detection.
- Report detection delay, false alarms, recovery behavior, and resource limits.
- Preserve the original default until evidence justifies replacing it.
- Do not claim control-algorithm development or production fleet operation from
  the integration demonstration.

## Implementation decisions

The gateway will use the existing versioned envelopes. A single durable SQLite
outbox owns run identity, sequence allocation, ordered sends, and acknowledgments.
ROS callbacks do not wait for Kafka. A successful send followed by a crash before
local acknowledgment deliberately retries the same envelope ID; downstream
idempotence, rather than a claim of transport exactly-once delivery, handles this.

Gateway reception time drives stream timing. ROS header time is preserved
separately with its clock domain, since simulation time and host UTC are not
interchangeable. A gateway health topic continues while a sensor is silent;
absence of both sensor and gateway evidence must not be presented as proof that
the physical sensor failed. Live sessions have an explicit duration and close
through the normal run lifecycle, while the process can start subsequent runs.
