# Architecture

## Design goals

The pipeline is designed for repeatable telemetry QA on a developer workstation
or a single CI/worker host. It prioritizes format tolerance, bounded ingestion
memory, explicit failure reporting, and inspectable columnar outputs without
requiring a ROS runtime.

## Data flow

```text
input roots
    |
    v
canonical discovery -----> bag_inventory.parquet
    |
    v
format adapter (.bag / ROS2 dir / .db3 / .mcap)
    |
    v
single-pass reader -----> topic_manifest.parquet
    |                  +-> message_index.parquet (streamed batches)
    |                  `-> selective payload fields (streamed batches)
    |                              |
    v                              v
timing/VSLAM checks          domain analyzers
    |                              |
    +-> topic_health.parquet       +-> domain_metrics.parquet
    +-> relationship_health        +-> anomaly_events.parquet
    +-> vslam_quality.parquet      `-> domain_summary.json
    |                              |
    `------------------------------+-> summary.json + bag_report.md

all bag outcomes -----> latest_run.json + latest_report.md
```

## Recorded streaming demo

ROS Workbench is a second execution path over selectable recordings: the
built-in deterministic MCAP fixture, installed public datasets, and uploads.
It does not replace the batch pipeline:

```text
ROS bag / MCAP recording
        |
        v
Python replayer -- versioned envelopes --> Kafka telemetry.events.v1
                                                |
                                                v
                                  Java Flink DataStream job
                                   |        |          |
                                   v        v          v
                              metrics   anomalies   late/dead-letter
                                   |        |          |
                                   `--------+----------'
                                            |
                              read-committed FastAPI projection
                                   |                   |
                                   v                   v
                          bounded SQLite          verified FileSink
                                   |                   summaries
                                   `---------+---------'
                                             v
                                  React ROS Workbench + SSE
```

The replayer preserves source nanoseconds while allocating non-overlapping
stream-time epochs. Flink keys topic state by run, robot, and topic; a separate
robot-keyed branch owns global sequence evidence and the processing-time
liveness watchdog. Event-time windows, timers, accepted-late corrections, and
mission summaries therefore cannot cross run boundaries.

Active analytical state has no per-entry TTL: registration, accepted evidence,
deduplication, and open incidents live together until cleanup. Topic summaries
clear topic state only after the event-time lateness interval; abort/failure
clears it immediately. The robot watchdog and sequence processor clear state on
terminal lifecycle events. Robot health aggregation uses inactivity cleanup so
an early terminal signal cannot erase conditions before in-flight branch outputs
arrive. The 12-minute `state_ttl_minutes` setting applies only to the short-lived
registration and summary coordination barriers.

A checkpointed processing-time timer also clears each entire inactive key after
`RUN_STATE_IDLE_TIMEOUT_MS` (default 86,400,000 milliseconds / 24 hours), renewed
by incoming records. Compose passes this environment setting to both Flink
services. It must exceed the allowed-lateness and robot-silence timeouts. This is
an explicit inactivity bound, including pauses: topic keys receive only their
own telemetry and routed lifecycle events, so other active topics do not keep a
silent topic alive. Set the bound above the longest supported pause or topic
silence. Timer callbacks do not renew it, so abandoned runs cannot retain state
indefinitely. Full-run evidence remains in state until completion; this timeout
bounds abandoned-key lifetime, not memory use for an unlimited active recording.
State and timers restore together from checkpoints. Harness tests cover restoring
the current state layout; there is no upgrade test from an older checkpoint.

Kafka output IDs and revisions make projection replay idempotent. The SQLite
transaction stores each projected record and its next Kafka offset together.
`summary_ready` is not treated as completion: FastAPI independently requires
schema-valid topic summary records matching the declared expected topic count
in committed, non-in-progress part files before persisting the terminal state
and notifying the browser. On restart, the API resumes this verification from
the projected marker.

The container stack pins Apache Kafka 4.1.2, Apache Flink 2.2.1, the Flink
Kafka connector 5.0.0-2.2, and Java 17. The connector resolves Kafka client
4.2.0; Kafka's bidirectional protocol compatibility permits that client to
negotiate with the 4.1.2 broker. Transaction timeouts are 15 minutes on both
sides, and compile-time contract checks cover the exactly-once sink settings.

## Components

- `discovery.py` walks input roots, skips configured cache directories, treats a
  ROS2 metadata directory as one source, and resolves bag-ID collisions.
- `reader.py` adapts the supported storage formats to `rosbags.AnyReader`.
  Standalone DB3 and MCAP files receive temporary metadata wrappers derived from
  their own indexes; the source files are never modified.
- `analysis.py` computes rate/gap/dropout integrity and VSLAM timing checks from
  bag log/receive timestamps, so those checks include recorder transport jitter.
  Configured topic relationships and automatically discovered left/right pairs
  share the same timestamp-pairing engine; configured stereo relationships are
  also projected into the existing VSLAM output for compatibility.
- `domain.py` selectively deserializes supported ROS payloads during the reader's
  single pass and writes bounded, typed records. Raw payload bytes are never
  published. Deserialization failures become explicit records rather than bag
  failures.
- `domain_analysis.py` computes odometry, IMU, command-response, TF, diagnostic,
  and image metrics; groups anomaly events; and renders the deterministic bag
  report.
- `pipeline.py` owns fingerprint skips, staging, publication, run locking,
  failure isolation, and operational manifests.
- `assets.py` owns optional NVIDIA NGC sample downloads, size and SHA-256
  verification, safe tar extraction, and completion markers.
- `cli.py` is the public command contract used by both console scripts and the
  Makefile.

## Output contract

Outputs are partitioned by `bag_id`; one bad input cannot corrupt another bag's
published results. `summary.json` and run manifests carry `schema_version: 1`.
Breaking field changes require a schema-version increment and migration notes.
Bag IDs include a stable path hash. After complete discovery, each locked run
reconciles `bags/` against the current inventory and removes outputs for sources
that disappeared. Root, traversal, or fingerprint failures defer reconciliation
and preserve prior outputs until a complete scan can confirm removals.

`relationship_health.parquet` is the generic cross-topic contract. Each row
names the relationship and its source, identifies both topics, and reports
pairing coverage and skew. The narrower `vslam_quality.parquet` contract remains
available for continuity checks and stereo-specific consumers.

Bag summaries keep category counters disjoint: `topic_health_counts` covers
per-topic health, `quality_check_counts` covers continuity checks, and
`relationship_check_counts` covers cross-topic relationships. Top-level warning
and error totals combine all three categories once.

The domain output is deliberately layered. `domain_records/` contains the
normalized evidence extracted from supported payloads, `domain_metrics.parquet`
contains long-form calculated measures, `anomaly_events.parquet` contains
time-bounded findings, and `bag_report.md` presents those results for humans.
`summary.json` embeds a compact `domain_analysis` section without duplicating
every metric or event.

Parquet files use Zstandard compression. Message indexes and normalized domain
records are written in configurable batches. Domain analyzers load the derived
records for one bag at a time; they never load raw payload collections.

## Production boundaries

The current execution model is one local process per output root. The lock and
atomic staging model make it safe for scheduled jobs on one host, but this is
not a distributed queue or a cross-host lock. A multi-worker deployment should
assign disjoint output roots or replace local publication with transactional
object storage and a shared catalog.

The source fingerprint uses file names, sizes, and nanosecond modification
times. This makes normal reruns inexpensive. Regulated or forensic workflows
should add full content hashes and immutable source storage.

Kafka, Flink, and the projection are production-shaped components running on
one local stack; they are not a robot command or safety path. The optional
[live ROS 2 gateway](live-ros2.md) publishes the same event schema with a durable
outbox and QoS evidence, but clock synchronization, fleet partitioning and
authentication are not designed for production use.

## Live stream timing and recovery

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

## Offline incident explanations

Recording preparation extends the batch evidence flow with structured detector
provenance (`anomaly_event_evidence.parquet`), complete normalized events,
conservative grouping, and predefined explanations. Detector conditions and their
original anomaly rows retain their existing meaning. The batch analysis cache
version includes the new provenance artifact.

`incident_grouping.py` supplies source-bound stable event IDs and same-topic image
overlap grouping. `incident_explanations.py` validates provenance counts and
conditions, computes interval-specific delivery context from the complete message
index, and builds an explanation catalog with typed values and evidence references.
Related configured streams remain context; they are not merged into a causal claim.

`investigations.py` writes `events.parquet`, `event_evidence.parquet`, and
`incidents.json` into a new analysis directory. It records their digests and the
rule/configuration signatures before advancing `latest.json`. Evidence GET endpoints
verify identities and digests, serve paginated summaries/details, and support
targeted interval signal retrieval. Read requests do not run detectors, generate
explanations, or parse raw bags. Existing interval plots still read prepared
Parquet evidence.

The recording UI keeps generated incidents distinct from reviewed annotations and
the live/replay `anomaly_id` revision model. Source nanoseconds remain strings in
JSON; plots use relative recorded seconds. Missing evidence, unsupported detector
types, and stale bundles have distinct outcomes. See the
[recording guide](recording-investigations.md#generated-incident-explanations) and
[incident schema](../schemas/recording-incidents-v1.schema.json).

An explicit evidence-preparation POST with the Workbench request header starts a
child process for a registered, installed recording. A file lock serializes builds;
status is stored on disk and reported through GET. The frontend polls the job and
reloads evidence on completion; callback changes do not restart it. Failed staging
is cleaned up, and successful publication retains the current plus one previous
analysis. Interrupted attempts can be retried after an API restart. The child shares
the container's resource budget but has its own Python interpreter. When the API
runs as root, the child uses the evidence folder's UID/GID. The output mount is
writable; source recordings remain read-only. See the [rebuild contract](recording-investigations.md#rebuild-evidence-from-the-page)
for recovery and ownership details.

## Offline navigation comparisons

Navigation is independent of recording selection and the streaming services:

```text
frozen suite + baseline/candidate pose/contact evidence
    -> evaluate-navigation CLI -> input.json + evaluation.json + report.md
    -> browser-local validation -> paired comparison / inspector
```

The Python evaluator owns scoring, paired-map statistics and suite gates. The
JavaScript viewer checks display contracts, preserves invalid placeholders and
labels descriptive pair changes separately from the suite decision. Its imports
do not send files to the API. Digests check supplied identities; they do not
prove the provenance of a simulator or collector. Live capture and BARN scheduling
remain future work. See the [contract and limits](navigation-regression.md).

`demo/web/contracts/navigation-report.test.js` invokes the real CLI and feeds its
outputs into the UI validator. CI covers all four suite decisions, the rejected
baseline collision gate, bundled-example fidelity and the 10,000-pair boundary.

## Workbench frontend boundaries

`App.jsx` composes the four mounted workspaces. The shared shell owns accessible
tabs and the header; workspace selection owns URL and preference persistence.
`useWorkbenchState` owns catalog selection, uploads, replay requests, SSE recovery
and service readiness. Telemetry presentation, replay controls and the upload
dialog are separate components; their existing state transitions are unchanged.
Recording and Localization retain their feature-specific evidence fetching.

Shared CSS enters through `styles/tokens.css` and `styles/workbench.css`. The first
owns theme variables; the second owns foundations, shell and shared controls.
Feature styles keep their own investigation layouts. Avoid reintroducing global
legacy launch selectors or additional theme override files. Developer commands and
validation boundaries are in [Contributing](../CONTRIBUTING.md).
