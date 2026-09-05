# Flight Deck

[Back to README](../README.md)

The self-contained demo replays selectable ROS recordings through Kafka,
computes stateful event-time metrics in a Java Flink DataStream job, projects
revisions into SQLite through FastAPI, and presents the results in a responsive
React operations console. It includes the deterministic 90-second MCAP mission
for `robot-17`, installed public validation datasets, and user uploads.

Start the stack:

```bash
docker compose up --build
```

Then open:

- Flight Deck: [http://localhost:3000](http://localhost:3000)
- Projection API: [http://localhost:8000/api/runs/current/snapshot](http://localhost:8000/api/runs/current/snapshot)
- Flink dashboard: [http://localhost:8081](http://localhost:8081)

Choose an available dataset in the Flight Deck before starting a 1x or 5x
replay. The catalog includes the TUM fixtures plus the LILocBench, OpenLORIS,
and ARCO datasets in `configs/public_test_datasets.yaml`; datasets that have not
been downloaded or extracted remain visible but disabled. Uploads accept one
direct `.bag`, `.mcap`, or `.db3` recording at a time and persist in the local
`dataset-uploads` Docker volume. The built-in warehouse mission also supports
the 1x camera-dropout scenario for exercising late arrivals, gap detection, and
recovery. The demo includes:

- independent Kafka, Flink, projection, and replayer readiness
- bounded out-of-orderness, allowed lateness, idle-partition detection, and
  sliding event-time windows
- checkpointed Flink state and exactly-once Kafka sinks
- persistent replay epochs and transactional SQLite projection offsets
- independently verified per-topic summary files

For public recordings and uploads, cadence baselines count all messages in
representative active source-time windows, preserving batches and coincident
timestamps while excluding long outages. Recognized continuous sensor and
robot-state types stay monitored
when they stop early or become irregular; static transforms and known event
types are exempt. Custom or unknown message types need sustained regular
cadence across most of the recording and may have cadence monitoring disabled.
These inferred expectations are estimates: on-demand sensor streams and
recordings dominated by missing samples need an explicit sensor profile for
reliable thresholds. Per-upload profiles are not yet supported; the built-in
warehouse mission uses its declared configuration.

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
a future extension. See [`docs/architecture.md`](../docs/architecture.md) for the
data flow, [`configs/streaming_demo.yaml`](../configs/streaming_demo.yaml) for
runtime values, and [`schemas/`](../schemas/) for versioned JSON contracts.
