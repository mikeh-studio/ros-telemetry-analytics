# ROS Telemetry Analytics

Automatic, local-first ingestion and timing-quality analysis for ROS bag
telemetry. The pipeline discovers mixed bag formats, indexes message metadata in
streaming batches, runs configurable topic and VSLAM checks, and publishes
idempotent Parquet and JSON results.

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
    ├── message_index.parquet
    ├── topic_manifest.parquet
    ├── topic_health.parquet
    ├── vslam_quality.parquet
    └── summary.json
```

`message_index.parquet` contains one row per message with bag ID, global read
sequence, topic, message type, and nanosecond timestamp. Raw payloads are never
persisted or deserialized.

`summary.json` is the stable machine-readable contract for one bag.
`latest_run.json` records processed, skipped, and failed sources without hiding
partial batch failures. See [the example report](examples/sample_report.md).

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

Timestamps are bag log/receive times supplied by the recording container, not
message payload `header.stamp` values. Continuity and stereo skew therefore
measure recorder-observed transport timing, which includes middleware and
delivery jitter; they do not prove hardware sensor synchronization. Payloads
remain intentionally undeserialized.

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
- **Memory:** raw payloads are streamed and discarded. The compact timestamp
  index is loaded per bag for analytics.

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
the wheel, and smoke-tests the packaged CLI.

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
