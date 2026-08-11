# ROS Telemetry Analytics

Automatic, local-first analysis for ROS bag telemetry. The pipeline discovers
mixed bag formats, indexes message metadata in streaming batches, checks timing
and VSLAM health, selectively derives robot-state features from supported
payloads, and publishes idempotent Parquet, JSON, and Markdown results.

It runs on macOS or Linux with Python 3.11+ and does not require a ROS
installation, CUDA, Docker, a simulator, or GPU tooling.

> **Project status:** Alpha. The analysis is suitable for engineering triage and
> dataset QA, not safety-critical robot control or certification.

## What It Handles

- ROS 2 bag directories containing `metadata.yaml`
- Standalone ROS 2 SQLite `.db3` files
- Standalone ROS 2 `.mcap` files
- ROS 1 `.bag` files
- Multiple nested input roots in one run
- Per-bag failure isolation, source fingerprinting, and unchanged-input skips
- Streaming message-index writes for large recordings
- Payload-aware odometry, IMU, command, TF, diagnostics, and image analyzers
- Atomic per-bag output publication and an exclusive pipeline lock

Discovery emits one canonical record per logical bag. Contained DB3/MCAP files
are not double-counted, overlapping roots are deduplicated, and download caches
are excluded by default.

## Quick Start

```bash
git clone https://github.com/mikeh-studio/ros-telemetry-analytics.git
cd ros-telemetry-analytics
make setup
make test
```

Place bags anywhere under `data/raw/`, then run:

```bash
make discover
make analyze
```

When installed as a wheel rather than run from a repository checkout, relative
configuration and download paths are resolved from the directory where the CLI
is invoked. Run it from the workspace that should own the `data/` directory, or
pass absolute `--input` and `--output` paths.

Analyze arbitrary paths without changing configuration:

```bash
.venv/bin/ros-telemetry analyze \
  --input /path/to/recordings \
  --input /path/to/recording.mcap \
  --output data/bronze
```

## Real-Time Flight Deck Demo

The repository also includes a self-contained streaming system for practicing
Apache Flink against realistic robot telemetry. It replays a deterministic
90-second ROS 2 MCAP recording for `robot-17` through Kafka, computes stateful
event-time health metrics in a Java Flink DataStream job, projects results into
SQLite through FastAPI, and presents them in a responsive React operations
console. No ROS installation, live robot, cloud account, or external dataset is
required.

Start the complete stack with Docker Compose:

```bash
docker compose up --build
```

Then open:

- Flight Deck: [http://localhost:3000](http://localhost:3000)
- Projection API: [http://localhost:8000/api/runs/current/snapshot](http://localhost:8000/api/runs/current/snapshot)
- Flink dashboard: [http://localhost:8081](http://localhost:8081)

The Flight Deck reports Kafka, Flink-cluster, streaming-job, projection-API,
and MCAP-replayer readiness independently. Mission controls remain disabled
until all five authorities are ready, and an unavailable authority replaces
stale robot health with a reconnecting state.

From the Flight Deck, run either a clean mission at 1x/5x or the 1x camera
dropout scenario. The fault keeps the 60.0-second camera frame, holds the 61.0
and 62.0-second frames until 67.1 seconds, drops the remaining frames before
68.0 seconds, then recovers. This exercises bounded out-of-order event time,
gap detection, rate suppression, and the one-second recovery gate.

The streaming contract is intentionally operational rather than illustrative:

- `telemetry.events.v1` has four robot-keyed source partitions; metrics,
  anomalies, late events, and dead letters have durable one-partition topics.
- Flink uses two-second bounded out-of-orderness, five-second allowed lateness,
  three-second idle-partition detection, 10-second windows sliding every second,
  five-second checkpoints, and exactly-once Kafka sinks.
- Replay epochs persist across container restarts so event time never overlaps
  between runs; original MCAP timestamps remain available separately.
- FastAPI persists revisioned projections and the next consumed offset for each
  Kafka topic-partition in one SQLite transaction.
- Final per-topic summaries are checkpointed under
  `data/demo-output/<run-id>/topic_health/`; the API reads those files itself
  before showing a run as verified complete.

After a clean run completes, repeat the six-invariant batch comparison inside
the API container (replace the run ID shown in the Flight Deck):

```bash
docker compose exec api \
  python scripts/compare_demo_oracle.py <run-id> --root /app
```

The first release deliberately uses recorded MCAP replay as its only source.
A ROS 2 bridge remains a future extension: it can publish the same versioned
envelopes from a live robot without changing the Flink topology, projection
contract, or dashboard semantics.

To exercise checkpoint recovery during an active mission, run this from another
terminal. The command acts on Compose from the host; no container receives the
Docker socket.

```bash
./scripts/demo_recovery.sh
```

The fixture is generated deterministically on first startup at
`data/demo/warehouse_run_17.mcap` inside the persisted demo volume. Versioned
JSON contracts live in [`schemas/`](schemas/), while replay and analytics values
are centralized in [`configs/streaming_demo.yaml`](configs/streaming_demo.yaml).
Shared Python/Java formula cases live in
[`configs/health_math_contract_cases.json`](configs/health_math_contract_cases.json).

Reruns skip bags whose fingerprint already has a complete successful output.
Changes to analytics rules automatically invalidate cached results. Use
`--force` when the underlying analysis implementation changes without a release
or when every bag should be recomputed explicitly.

## Optional NVIDIA Sample Assets

```bash
make download-visual-slam
make download-nvblox
```

These optional NVIDIA Isaac ROS archives provide external ROS2 validation data;
they are not required to run the pipeline. Archives are stored under
`data/raw/downloads/` and extracted under `data/raw/isaac_ros_assets/`. The
downloader enforces the configured version, byte size, and SHA-256 checksum,
rejects unsafe tar members, and publishes an extraction only after it
completes. A failed pinned download never falls back to a mutable `latest`
asset. The current nvblox archive is approximately 9.3 GB.

NVIDIA assets are not included in this repository and remain subject to their
upstream terms. This independent project is not affiliated with or endorsed by
NVIDIA; NVIDIA, Isaac, and related names are trademarks of their respective
owners.

## Outputs

Each bag is published independently:

```text
data/bronze/
├── bag_inventory.parquet
├── latest_report.md
├── latest_run.json
├── runs/<run-id>.json
└── bags/<bag-id>/
    ├── anomaly_events.parquet
    ├── bag_report.md
    ├── domain_metrics.parquet
    ├── domain_summary.json
    ├── message_index.parquet
    ├── relationship_health.parquet
    ├── topic_manifest.parquet
    ├── topic_health.parquet
    ├── vslam_quality.parquet
    ├── domain_records/
    │   ├── commands.parquet
    │   ├── diagnostics.parquet
    │   ├── extraction_errors.parquet
    │   ├── images.parquet
    │   ├── imu.parquet
    │   ├── odometry.parquet
    │   └── transforms.parquet
    └── summary.json
```

`message_index.parquet` contains one row per message with bag ID, global read
sequence, topic, message type, and nanosecond timestamp. Supported payloads are
selectively deserialized during that same streaming pass, but raw payloads are
never persisted. Only typed, derived fields and bounded image features are
written under `domain_records/`.

`summary.json` is the stable machine-readable contract for one bag.
`bag_report.md` is the shareable engineering summary, while
`domain_metrics.parquet` and `anomaly_events.parquet` retain the evidence behind
that narrative. Payloads that cannot be deserialized are recorded in
`extraction_errors.parquet` without hiding the timing analysis for the bag.
`latest_run.json` records processed, skipped, and failed sources without hiding
partial batch failures. See the sanitized [data-health example](examples/sample_report.md)
and [domain-analysis example](examples/sample_domain_report.md).

## Analysis

Topic health reports:

- message count, duration, mean rate, and expected-rate ratio
- maximum and p95 inter-message gaps
- threshold-crossing gap events and estimated dropped messages
- `ok`, `warn`, or `error` status

VSLAM quality reports:

- `/tf`, pose, odometry, and visual-SLAM continuity
- nearest-timestamp stereo pairing within a configurable window
- unmatched left/right frames
- maximum, mean, and p95 stereo skew
- configurable warning thresholds

Topic relationships report timestamp pairing for explicitly named topic pairs.
This covers datasets whose sensor names do not follow the automatic
`/left/...` and `/right/...` stereo convention. Relationships can be required
or optional and may override the global pairing and skew thresholds:

```yaml
analytics:
  topic_relationships:
    - name: front_stereo
      type: stereo_sync
      topic_a: /cam0/image_raw
      topic_b: /cam1/image_raw
      required: true
      pairing_window_ms: 20.0
      skew_warn_ms: 5.0
```

`relationship_health.parquet` identifies whether each relationship came from
configuration or automatic stereo discovery and records paired counts,
unmatched counts, skew statistics, status, and diagnostic detail. A configured
relationship is evaluated only for bags containing at least one of its topics,
which allows one pipeline configuration to cover heterogeneous datasets. If
only one side is present, `required: true` reports an error and
`required: false` reports a warning.

### Domain analyzers

The domain lane analyzes what happened during the recorded robot run:

- **Odometry:** distance traveled, duration, mean/maximum speed, stationary
  fraction, covariance traces, and pose jumps.
- **IMU:** acceleration and angular-velocity magnitude, configured threshold
  intervals, orientation, and covariance traces.
- **Command response:** configured Twist command topics matched to nearby
  odometry, speed-tracking error, and command-without-motion intervals.
- **TF:** frame pairs, connected components, empty/self frames, directed cycles,
  per-pair translation path/speed, and translation jumps.
- **Diagnostics:** OK/warn/error/stale counts plus grouped non-OK intervals and
  preserved key/value evidence.
- **Images:** dimensions, encoding, payload size, sampled 8/16-bit intensity,
  adjacent-pixel sharpness heuristic, depth-image mean/valid coverage, and
  consecutive duplicate hashes. Raw images are not published.

Thresholds and command-topic patterns live under `analytics.domain_analyzers`
in [`configs/pipeline.yaml`](configs/pipeline.yaml). Set `enabled: false` to keep
the output contract but skip payload deserialization and domain calculations.
The default threshold values are portable starting points and should be tuned
to the robot, environment, and mission profile.

Timestamps are bag log/receive times supplied by the recording container, not
message payload `header.stamp` values. Topic-health continuity and stereo skew
therefore measure recorder-observed transport timing, which includes middleware
and delivery jitter; they do not prove hardware sensor synchronization. Domain
records retain supported payload header stamps separately when present.

All rules live in [`configs/pipeline.yaml`](configs/pipeline.yaml). Topic-rate
rules are evaluated top-to-bottom as regular expressions. This keeps sensor
cadence assumptions explicit instead of embedding them in code.

## Reliability Model

- **Idempotency:** source size/mtime metadata produces a stable fingerprint;
  successful unchanged bags are skipped.
- **Failure isolation:** a malformed bag is recorded as failed while remaining
  bags continue unless `--fail-fast` is set; unattempted remainder entries are
  still recorded explicitly.
- **Atomicity:** files are built under `.staging/`; the final bag directory is
  replaced only after ingestion and analysis succeed. Interrupted staging and
  backup directories are recovered or removed on the next run.
- **Reconciliation:** outputs for sources no longer present in the current
  inventory are removed while the output lock is held.
- **Concurrency:** one process may publish to an output root at a time on a
  local filesystem. POSIX advisory locks are not a distributed lock and may not
  be enforced by every network filesystem.
- **Memory:** raw payloads are deserialized one at a time for supported domains,
  reduced to typed fields/features, and discarded. Parquet writes remain
  batched; no full raw-payload collection is retained in memory.

The fingerprint is designed for efficient local change detection, not
cryptographic proof of a multi-gigabyte bag's content. Hash the source files
externally when chain-of-custody guarantees are required.

An analysis run that discovers zero bags exits nonzero so an empty or unmounted
input directory cannot look healthy in automation.

## Development

```bash
make format
make lint
make test
```

CI runs lint, formatting, and the test suite on Python 3.11, 3.12, and 3.13.
The local test gate requires at least 80% branch-aware coverage and uses only
generated fixtures. CI also builds the source and wheel distributions, installs
the wheel, and smoke-tests the packaged CLI. Dedicated jobs compile/test the
Java 17 Flink application and test/build the React dashboard. The Compose lane
builds every image, runs a deterministic clean mission, compares all six batch
invariants, then verifies the completed and failure-state UI in headless
Chromium before tearing down volumes.

For implementation boundaries and data flow, see
[`docs/architecture.md`](docs/architecture.md). Security reports should follow
[`SECURITY.md`](SECURITY.md); contribution expectations are in
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Public Test Corpus

Optional public datasets are stored under `data/raw/public_datasets/` and remain
ignored by Git. Their sources, checksums, licenses, validation results, and known
analytics caveats are recorded in
[`configs/public_test_datasets.yaml`](configs/public_test_datasets.yaml).

Run the validated TUM RGB-D and TUM VI corpus independently of the optional
NVIDIA sample data:

```bash
make analyze-public-data
```

Legacy ROS parser fixtures are intentionally excluded from this command because
several are malformed, use unsupported historical bag versions, or are expensive
to decompress. They are retained as explicit failure and compatibility cases.

The generated test suite exercises ROS2 SQLite and MCAP containers end to end,
including stereo timing. The optional NVIDIA Visual SLAM sample provides a
larger external ROS2 SQLite validation case; TUM supplies independent ROS1
coverage.

## License

The source code is available under the [MIT License](LICENSE). ROS bag data,
NVIDIA assets, and other third-party inputs retain their own licenses.
