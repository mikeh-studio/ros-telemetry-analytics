# ROS Workbench

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

- ROS Workbench: [http://localhost:3000](http://localhost:3000)
- Projection API: [http://localhost:8000/api/runs/current/snapshot](http://localhost:8000/api/runs/current/snapshot)
- Flink dashboard: [http://localhost:8081](http://localhost:8081)

Choose an available dataset in ROS Workbench before starting a 1x or 5x
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

The main **Monitored Topics** view lists the topics observed in the selected
run, with a short explanation of their role, delivery health, and incident onset
when available. Selecting a signal opens its longer explanation and inspection
details. Topics with rate monitoring disabled show their latest retained update
instead of a rate target. Delivery health does not establish sensor accuracy.

Gateway streams live in a separate, collapsible **Telemetry Pipeline** section.
Delivery faults open it automatically and display a notice above the robot
signals. Gateway events show observed time, type, affected topic, severity when
reported, and available attributes; silence is not treated as a rate fault.
Event evidence uses the existing sampled projection (first accepted observation
per topic per second, retaining up to 180 samples per topic), so it is not a
complete event log. Earlier events do not establish that a fault remains active.
All streams remain included in monitoring, incident evidence, and summary
verification; the grouping changes their presentation.

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

For live gateway and Nav2 configuration, see [Live ROS 2](live-ros2.md).
See [`docs/architecture.md`](../docs/architecture.md) for the
data flow, [`configs/streaming_demo.yaml`](../configs/streaming_demo.yaml) for
runtime values, and [`schemas/`](../schemas/) for versioned JSON contracts.

The grouping regression tests use recorded-demo and Nav2 API fixtures and can
run against a local Vite server with WebKit, without Chrome:

```bash
cd demo/web
npx playwright install webkit
# Start npm run dev in another terminal.
FLIGHT_DECK_BROWSER=webkit npm run test:e2e -- e2e/signal-groups.spec.js
```

These browser fixtures validate presentation and interaction; they do not replace
a live ROS/Kafka/Flink end-to-end run.

## Localization investigation

Choose the **Localization Investigation** tab beside **Telemetry Health** to inspect
the separate saved evaluation. Telemetry Health also includes a direct entry point.
Switching tabs preserves the selected event, filter, and playback cursor, and
pauses investigation playback when leaving it. The tab controls support
Left/Right arrows and Home/End for keyboard navigation.
The recording name, duration, configuration fingerprint, and detector version
(if recorded) identify the evidence. Aggregate scores and recorded thresholds
are under **Evaluation results and detector configuration**.

Filter detected events, missed events, or false alarms, then select a case.
Previous/next event controls traverse the selected category. Each case loads
full-resolution samples spanning its labeled and matched detector interval,
with up to five seconds of context on either side. The interval stays within
one run, source file, and segment; the faint route shows a sampled overview of
that same segment. This playback clock is independent of mission replay.

Play/pause, speed, looping, sample stepping, and the time slider control both
position markers and the evidence charts. Clicking an evidence chart also sets
the shared time cursor. Missing samples and recording boundaries break plotted
lines; position markers disappear within gaps. Duplicate timestamps remain
available through sample stepping. Position error and published failure labels
are evaluation-only; particle spread, pose jumps, detector scores, and alert
state are operational signals. Heading spread appears when configured.

**Why this outcome?** reports the saved event match, threshold crossings,
detection delay, and recovery timing. It does not infer a physical cause or
rerun the detector. Missing inputs are disclosed. Event-matching and recovery
settings can explain why a crossing does not produce a matched event.

The read-only `/api/localization/interval` endpoint requires the case ID and
evaluation fingerprint from `/api/localization/evaluation`. It rejects stale
evaluation selections and intervals exceeding 25,000 samples instead of silently
downsampling investigative evidence. Older evaluations without the necessary
artifacts retain their saved overview and scores, with an explicit notice that
detailed investigation is unavailable.
