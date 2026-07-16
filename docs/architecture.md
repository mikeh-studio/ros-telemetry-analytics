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
Bag IDs include a stable path hash. Each locked run reconciles `bags/` against
the current inventory and removes outputs for sources that disappeared.

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
