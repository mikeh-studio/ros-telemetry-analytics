# Recorded-bag analysis

[Back to README](../README.md)

## Inputs

- ROS 2 bag directories containing `metadata.yaml`
- Standalone ROS 2 SQLite `.db3` and `.mcap` files
- ROS 1 `.bag` files
- Multiple nested input roots in one run

Discovery emits one canonical record per logical bag. Contained DB3/MCAP files
are not double-counted, overlapping roots are deduplicated, and download caches
are excluded by default.

## Analyze recordings

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
[data-health](../examples/sample_report.md) and
[domain-analysis](../examples/sample_domain_report.md) examples.

## Analysis

### Timing and relationships

- message counts, duration, mean rate, and expected-rate ratio
- maximum and p95 inter-message gaps, gap events, and estimated drops
- `/tf`, pose, odometry, and visual-SLAM continuity
- automatic stereo discovery and configurable topic-pair relationships
- pairing coverage, unmatched frames, and maximum/mean/p95 skew

Relationships are configured in [`configs/pipeline.yaml`](../configs/pipeline.yaml)
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

## Reliability model

- **Idempotency:** successful bags with unchanged source fingerprints are
  skipped; analytics-rule changes invalidate cached results.
- **Failure isolation:** malformed bags are reported while remaining bags
  continue unless `--fail-fast` is set.
- **Atomicity:** results are staged and published only after analysis succeeds;
  interrupted staging and backups are reconciled on the next run.
- **Reconciliation:** outputs for removed sources are deleted only after complete
  discovery, while the output lock is held. Discovery failures preserve prior
  outputs until a complete scan can confirm removals.
- **Concurrency:** one process may publish to an output root at a time on a
  local filesystem; the lock is not distributed.
- **Memory:** raw payloads are processed one at a time and discarded, while
  Parquet writes remain batched.

Fingerprints use names, sizes, and nanosecond modification times for efficient
local change detection; hash source contents separately when chain-of-custody
guarantees are required. A run that discovers zero bags exits nonzero so an
empty or unmounted input directory cannot appear healthy in automation.
