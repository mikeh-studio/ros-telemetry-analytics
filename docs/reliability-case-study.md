# From recorded replay to tested robot telemetry recovery

The project began as a one-robot recorded-replay observability system. This work
adds a live ROS 2 gateway and tests what happens when telemetry becomes
incompatible, duplicated, delayed, disconnected, or interrupted by process loss.
The scope remains robotics data and observability engineering. Integrating Nav2
does not demonstrate a new navigation controller or production fleet operation.

## What the localization evaluation changed

A frozen environment split covers 21 published simulation runs. Fifteen runs
guide detector selection; six runs evaluate the selected candidate. Lowering the
particle-spread threshold from 0.40 m to 0.36 m improves held-out macro sample
recall from 36.2% to 45.5%, while precision falls from 92.4% to 85.7%. False alarms
also increase on evaluation runs. The default remains 0.40 m; the candidate is
opt-in. Better recall is a measured tradeoff, not a solved failure-detection task.

See [the study](../examples/localization_study.md) for per-run results and unmatched
events. Ground truth is used for scoring, not detector input.

## Live integration and fault evidence

The gateway preserves ROS header time and coordinate frames while using reception
time for stream timing. A bounded SQLite outbox owns sequence numbers and retry
identities. A separate Nav2/Gazebo mission completed with about 0.98 m of odometry
displacement and 2,350 summarized gateway observations. DDS fault fixtures are
reported separately from this navigation evidence.

| Experiment | Observed result | What it establishes |
| --- | --- | --- |
| Controlled Nav2 estimate disturbance | 2 m reset; 1,504 observations reconciled; one disagreement and recovery | Post-run detection from live AMCL/odometry signals, with manual restoration |
| QoS mismatch and repair | Direct incompatibility callback; recovery visible 3.088 s after repair | Middleware evidence distinguishes incompatible delivery from publication silence |
| Duplicate transport | Ten duplicate deliveries; 1,637 unique observations counted once | Identity-based analytical accounting in this fixture |
| Delayed transport | Ten events rejected in final validation; 1,629 observations summarized | Watermark-based disposition and source reconciliation |
| Edge overflow and restart | 1,378 accepted observations summarized; 405 explicit rejections; all incidents recovered | Bounded storage with visible loss and stable persisted retry records |
| Three simultaneous robots | 64.944 s overlap; both controls incident-free with 2,126 observations each | A gateway outage on one stream did not corrupt the two controls in this experiment |
| Projection API restart | 18 s outage; committed-data boundary reached in 1.158 s; 2,297 observations summarized | Durable API projection catch-up on the local stack |
| Flink worker restart | Checkpoint restoration and a newer checkpoint in 46.898 s; 3,617 observations summarized without unexpected incidents | Worker recovery with the JobManager, Kafka, and API still running |

The localization diagnostic uses relative motion from an initially consistent
AMCL/odometry pair. Injection labels and known spawn coordinates enter scoring
only. Its short stationary validation does not establish moving-robot accuracy,
production alerting, or an improvement to the separate TUHH benchmark. See
[the telemetry results](../examples/nav2_telemetry_results.json).

## Failures that changed the implementation or evaluation

- Startup discovery produced misleading live rate alerts. Rate incidents now
  require a complete post-grace window.
- A one-second recovery gate required three messages from a 1 Hz topic. The gate
  now scales to the configured rate, allowing the slow stream to recover.
- Buffered recovery timestamps and projection ordering could leave an incident
  active. Recovery decisions preserve timing order, and newer anomaly revisions
  take precedence in the API.
- A delay experiment disproved the assumption that ten seconds of wall delay
  always means rejection. Four events were accepted late and six rejected in
  development; watermark evidence and counters explain the distinction.
- An API catch-up verifier incorrectly required transaction-marker offsets as
  projected data offsets. Its replacement freezes committed data-record
  boundaries. The original failed report remains available.
- Flink checkpoint restoration initially produced a false robot-offline alert.
  A fresh timer interval alone still failed when source startup took longer.
  The repair waits for source progress or accepted input and preserves unknown
  health while observation is unavailable. Final runtime validation passes with
  no unexpected incidents; both failed attempts remain in the results.

The unified ten-case run passes, including both service restarts and the final
Nav2 diagnostic. The initial suite attempt remains failed because one eligible
odometry publication was absent before gateway acceptance; all accepted messages
still reconciled. The repeat used the same source gate. This distinction prevents
successful downstream accounting from hiding missing upstream data. Both results
are retained in [the suite evidence](../examples/reliability_suite_results.json).

## Reproduction and limits

[The runbook](live-ros2.md) gives the experiment commands.
[The roadmap](reliability-roadmap.md) records each implementation and verification gate. Raw experiment directories retain publisher ledgers, source
captures, snapshots, injection identities, and failed candidate reports; compact
results are checked into `examples/`.

Position plots show sampled reported coordinates, grouped by topic and frame.
They are not ground truth and cannot establish localization correctness. The
public labeled localization recording is separate from each live incident.
Browser review of a live QoS incident and recovery passes; it also exposed rounded
nanosecond displays, which now carry an approximate label. See the
[browser review evidence](../examples/browser_review_results.json). These small local experiments do not
measure production capacity, guarantee sensor delivery during gateway downtime,
or establish JobManager disaster recovery.
