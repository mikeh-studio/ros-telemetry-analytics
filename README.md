# ROS Telemetry Analytics

Local-first analysis for recorded ROS telemetry. The project discovers ROS 1
and ROS 2 bags, checks timing and sensor-stream health, derives selected robot
state features, and publishes inspectable Parquet, JSON, and Markdown results.

It is designed for robotics platform, reliability, and data engineers who need
to triage runs or validate datasets without installing ROS, CUDA, a simulator,
or GPU tooling. It runs on macOS and Linux with Python 3.11+.

> **Project status:** Alpha. The analysis supports engineering triage and
> dataset QA, not safety-critical control or certification.

## Two Workflows

- **Recorded-bag analysis:** process mixed ROS bag formats into repeatable
  timing, relationship, and payload-derived evidence.
- **Localization integrity evaluation:** score an observable-only AMCL failure
  detector against published ground-truth trajectories and failure labels.
- **Real-time Flight Deck:** replay a deterministic ROS 2 MCAP fixture through
  Kafka and Apache Flink, then inspect event-time health in a React console.

The Flight Deck is a streaming demonstration of the same telemetry-health
ideas; it does not replace the batch pipeline.

## Quick Start

```bash
git clone https://github.com/mikeh-studio/ros-telemetry-analytics.git
cd ros-telemetry-analytics
make setup
make test
```

Place bags under `data/raw/`, then run:

```bash
make discover
make analyze
```

Analyze arbitrary paths without changing configuration:

```bash
.venv/bin/ros-telemetry analyze \
  --input /path/to/recordings \
  --input /path/to/recording.mcap \
  --output data/bronze
```

When installed as a wheel, relative configuration and data paths are resolved
from the current working directory. Run the CLI from the workspace that should
own `data/`, or pass absolute input and output paths.

## Supported Inputs

- ROS 2 bag directories containing `metadata.yaml`
- Standalone ROS 2 SQLite `.db3` and `.mcap` files
- ROS 1 `.bag` files
- Multiple nested input roots in one run

Discovery emits one canonical record per logical bag. Contained DB3/MCAP files
are not double-counted, overlapping roots are deduplicated, and download caches
are excluded by default.

## Real-Time Flight Deck

The self-contained demo replays a deterministic 90-second MCAP mission for
`robot-17` through Kafka, computes stateful event-time metrics in a Java Flink
DataStream job, projects revisions into SQLite through FastAPI, and presents the
results in a responsive React operations console.

Start the stack:

```bash
docker compose up --build
```

Then open:

- Flight Deck: [http://localhost:3000](http://localhost:3000)
- Projection API: [http://localhost:8000/api/runs/current/snapshot](http://localhost:8000/api/runs/current/snapshot)
- Flink dashboard: [http://localhost:8081](http://localhost:8081)

Run a clean mission at 1x or 5x, or use the 1x camera-dropout scenario to
exercise late arrivals, gap detection, and recovery. The demo includes:

- independent Kafka, Flink, projection, and replayer readiness
- bounded out-of-orderness, allowed lateness, idle-partition detection, and
  sliding event-time windows
- checkpointed Flink state and exactly-once Kafka sinks
- persistent replay epochs and transactional SQLite projection offsets
- independently verified per-topic summary files

Exercise TaskManager checkpoint recovery during an active mission:

```bash
./scripts/demo_recovery.sh
```

Compare a completed clean run with the batch-analysis oracle:

```bash
docker compose exec api \
  python scripts/compare_demo_oracle.py <run-id> --root /app
```

Recorded replay is the only source in this release; a live ROS 2 bridge remains
a future extension. See [`docs/architecture.md`](docs/architecture.md) for the
data flow, [`configs/streaming_demo.yaml`](configs/streaming_demo.yaml) for
runtime values, and [`schemas/`](schemas/) for versioned JSON contracts.

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

`message_index.parquet` contains one row per message with its bag ID, read
sequence, topic, type, and nanosecond timestamp. Supported payloads are reduced
to typed fields and bounded image features under `domain_records/`; raw payloads
and images are not published.

`summary.json` is the stable machine-readable bag contract, while
`bag_report.md` is the shareable engineering summary. Deserialization failures
are recorded without hiding timing results, and `latest_run.json` reports
processed, skipped, and failed sources. See the sanitized
[data-health](examples/sample_report.md) and
[domain-analysis](examples/sample_domain_report.md) examples.

## Localization Integrity Evaluation

The evaluator supports the processed Parquet files from the public
[TUHH Robot Localization Failure Prediction Dataset](https://doi.org/10.15480/882.15836).
Download and extract the upstream `preprocessed_data.zip`, then provide one or
more processed members from the same or different experiment runs:

```bash
.venv/bin/ros-telemetry evaluate-localization \
  --input /path/to/parquets/processed/rec_20250821_104113_id_01.processed.parquet \
  --input /path/to/parquets/processed/rec_20250821_104113_id_02.processed.parquet \
  --output data/evaluations/rec_20250821_104113
```

The baseline detector uses only particle-cloud position spread and consecutive
AMCL pose jumps. Ground-truth pose, published position/heading errors, and
`is_delocalized` are kept on the scoring side of the contract. This prevents
label leakage from turning the benchmark into a tautological threshold check.

Each evaluation writes:

```text
localization_samples.parquet
localization_events.parquet
localization_event_matches.parquet
localization_eval.json
localization_eval.md
```

On the complete published warehouse run `rec_20250821_104113`, the unchanged
baseline produced **0.856 sample precision**, **0.468 sample recall**, and
**0.605 sample F1**. After merging label flicker separated by at most 500 ms,
event precision was **0.842** and event recall was **0.667** using one-to-one
event matching. The result is a
starting benchmark, not a tuned model; its modest sample recall makes the next
improvement target explicit. See the committed
[sample evaluation](examples/sample_localization_eval.md) and
[`configs/public_test_datasets.yaml`](configs/public_test_datasets.yaml) for the
source manifest and exact thresholds.

## Analysis

### Timing and relationships

- message counts, duration, mean rate, and expected-rate ratio
- maximum and p95 inter-message gaps, gap events, and estimated drops
- `/tf`, pose, odometry, and visual-SLAM continuity
- automatic stereo discovery and configurable topic-pair relationships
- pairing coverage, unmatched frames, and maximum/mean/p95 skew

Relationships are configured in [`configs/pipeline.yaml`](configs/pipeline.yaml)
and can be required or optional. One configuration may cover heterogeneous bags;
relationships are evaluated only when at least one named topic is present.

### Domain analyzers

- **Odometry:** distance, speed, stationary fraction, covariance, and pose jumps
- **IMU:** acceleration, angular velocity, threshold intervals, and covariance
- **Command response:** Twist commands matched to nearby odometry and motion
- **TF:** frame connectivity, cycles, translation paths, speed, and jumps
- **Diagnostics:** grouped non-OK intervals with preserved key/value evidence
- **Images:** dimensions, encoding, bounded intensity/sharpness/depth features,
  and duplicate hashes

Thresholds and command-topic patterns live under `analytics.domain_analyzers` in
`configs/pipeline.yaml`. Disable that lane to retain the output contract while
skipping payload deserialization and domain calculations.

Timing checks use bag log/receive timestamps, not payload `header.stamp` values,
so they include middleware and recorder jitter and do not prove hardware sensor
synchronization. Supported domain records retain header stamps when available.

## Reliability Model

- **Idempotency:** successful bags with unchanged source fingerprints are
  skipped; analytics-rule changes invalidate cached results.
- **Failure isolation:** malformed bags are reported while remaining bags
  continue unless `--fail-fast` is set.
- **Atomicity:** results are staged and published only after analysis succeeds;
  interrupted staging and backups are reconciled on the next run.
- **Reconciliation:** outputs for removed sources are deleted while the output
  lock is held.
- **Concurrency:** one process may publish to an output root at a time on a
  local filesystem; the lock is not distributed.
- **Memory:** raw payloads are processed one at a time and discarded, while
  Parquet writes remain batched.

Fingerprints use names, sizes, and nanosecond modification times for efficient
local change detection; hash source contents separately when chain-of-custody
guarantees are required. A run that discovers zero bags exits nonzero so an
empty or unmounted input directory cannot appear healthy in automation.

## Optional Validation Data

Validated TUM RGB-D and TUM VI datasets provide independent ROS 1 coverage and
healthy-data robustness checks:

```bash
make analyze-public-data
```

Optional NVIDIA Isaac ROS archives provide larger ROS 2 validation cases:

```bash
make download-visual-slam
make download-nvblox
```

Downloads remain ignored by Git. Their sources, checksums, licenses, validation
results, and known caveats are recorded in
[`configs/public_test_datasets.yaml`](configs/public_test_datasets.yaml) and the
[`asset configuration`](configs/asset_sources.yaml). NVIDIA data is subject to
upstream terms; this independent project is not affiliated with or endorsed by
NVIDIA.

## Development

```bash
make format
make lint
make test
```

CI tests Python 3.11, 3.12, and 3.13, builds and reinstalls the package, compiles
the Java Flink job, builds/tests the React dashboard, and exercises the complete
Compose stack with clean and camera-dropout missions.

For implementation boundaries, see [`docs/architecture.md`](docs/architecture.md).
Security reports should follow [`SECURITY.md`](SECURITY.md); contribution
expectations are in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

The source code is available under the [MIT License](LICENSE). ROS bag data,
NVIDIA assets, and other third-party inputs retain their own licenses.
