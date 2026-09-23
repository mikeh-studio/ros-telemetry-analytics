# Recording investigations and dataset audit

Implemented from the [reviewed plan](dataset-evaluation-and-workbench-plan.md). Seven real recordings are prepared locally, including all four additions. The **Recording** tab works without a replay. It provides versioned evidence, interval selection, three aligned plots with a shared recorded-time cursor, bounded image/scan previews, event details, and topic coverage.

## Generated incident explanations

Choose a prepared recording, then select an entry under **Detected incidents**.
The explanation shows measured observations, linked evidence, untested possible
explanations, explicit limitations, and next checks. Select an **Inspect** button
to focus the corresponding signal or original detector evidence. The source
previews identify whether they fall inside the incident or provide surrounding
context. Moving the cursor does not change the explanation.

Explanations run entirely offline using deterministic rules. Supported families
are image brightness/sharpness, recorded delivery gaps (including separately
labeled reference coverage), and command/odometry disagreement. Other detector
types remain visible with a factual fallback. No warnings means no configured
warnings were detected, not that the recording is known to be healthy.

Only compatible same-topic image warnings that overlap the original seed can
merge, with a ten-second maximum combined span. Other detector episodes remain
separate. Configured counterpart streams can appear as inspection context;
grouping and temporal overlap do not establish a common cause. Motion explanations
retain the actual odometry selection, nearest-sample offsets, both speed
thresholds, and frame limitations.

**Reviewed examples** remain separate human-authored case notes. Selecting
a reviewed case or manually submitting a new interval clears the selected
generated explanation. Uploads still need separate offline preparation; live
incident explanation and automatic baseline comparison are not part of this release.

Click **Rebuild evidence** after upgrading: old bundles are stale by
design when analysis or explanation rules change. New UUID directories preserve
earlier evidence. The packaged catalog is
`src/ros_telemetry_analytics/default_incident_explanations.yaml`, with validated
repository overrides in `configs/incident_explanations.yaml`. These rules do not
change the detector thresholds in analysis profiles.

Each prepared bundle adds `events.parquet`, `event_evidence.parquet`, and
`incidents.json`. Complete event membership is retained before any UI limits.
Incident summaries and original warnings are paginated; the panel exposes exact
counts, rule versions, source identity, and bounded source-sample examples.
Source and incident artifact digests are checked before cached explanations are served.

Read-only endpoints, all requiring the exact `analysis_id`:

- `GET /api/investigations/{dataset_id}/incidents?analysis_id=...&offset=0&limit=50`
  lists incident summaries (maximum 100 per page). Optional `start_s`/`end_s`
  filter overlapping incidents without regrouping them.
- `GET /api/investigations/{dataset_id}/incidents/{incident_id}?analysis_id=...&member_offset=0&member_limit=50`
  returns the explanation and a page of original warnings (maximum 100 per page).
- The existing interval route accepts `topic` and `field` to retrieve a specific
  supporting signal before the display-series limit is applied.

The [2026-09-22 validation snapshot](../examples/incident_explanation_validation_20260922_b031c10089ab4ed3b7477ac75cf8011c.json)
records 317,443 messages across seven recordings, 270 warnings represented as
261 incidents, unchanged domain-detector outputs against previous preparations,
and three source-backed case checks. Freiburg 1 XYZ had no configured warnings;
unsupported/missing-evidence behavior is covered with synthetic tests rather than
invented real-data examples. That snapshot predates the final UI cleanup; it is retained as dated source-evidence
validation. See the [PR validation record](pr-recording-explanations-validation.md)
for the final code checks and refreshed screenshots. These checks do not establish
physical root causes or production-fleet readiness.

The synthetic browser flow needs no downloaded recordings. To additionally run
the local prepared-data check, set `RECORDING_INCIDENTS_LIVE=1`,
`RECORDING_INCIDENTS_API` to the local API URL, and `FLIGHT_DECK_BASE_URL` to the
frontend URL, then run:

```bash
npm --prefix demo/web run test:e2e -- recording-incidents.spec.js
```

See the [implementation plan](incident-explanation-plan.md) for contract and
grouping decisions.

## Review now

Open ROS Workbench, choose **Recording**, then select:

1. **TUM VI · Room 4 → Can image usefulness fall while frame delivery stays steady?** The 100.8–105 s window shows dark/low-texture image content with steady frame delivery. Inspect the six source images and compare a nominal interval near the start.
2. **TUM VI · Room 4 → Is this delivery warning on a sensor or on reference tracking?** The 44–47 s window shows a 483.334 ms reference-pose gap alongside continuing camera/IMU delivery. This limits evaluation coverage; it does not establish sensor failure.
3. **LILocBench · Dynamics 0 → Does a command-without-motion warning establish a physical failure?** The 64.5–67.5 s window shows a short command/odometry disagreement, scan context, and the surrounding turning transition. Switch motion signals to `angular_z` to explore the alternative explanation.

Annotations are in [recording_cases.yaml](../configs/recording_cases.yaml), separate from generated events. They are bound to both the source SHA-256 and the exact prepared analysis ID. Manually choosing another interval leaves the curated case and returns to exploration.

## Reproduce locally

Use the repository Python environment with its `demo` dependencies installed. Downloads are public recordings subject to the source terms listed in the manifest; raw data and derived evidence stay gitignored.

```bash
.venv/bin/python scripts/fetch_comparison_data.py
.venv/bin/python scripts/prepare_investigations.py
.venv/bin/python scripts/audit_dataset_inventory.py
```

The download command fetches only the four comparison bags and three LILocBench reference trajectories; it does not replace existing files. It rejects HTML, validates expected sizes where recorded and bag magic, and saves acquisition receipts. Existing local TUM RGB-D XYZ, TUM VI Room 4 and LILocBench Dynamics are prerequisites for the complete seven-recording pack. Their source URLs are in the existing public dataset manifest. Missing recordings remain explicitly unavailable.

To prepare one recording: append its registered ID, for example `tum_vi_room4_512`. Preparation publishes a new UUID directory and updates `latest.json` only after successful extraction and source checks. Previous evidence remains intact. To update only reviewed annotation text after editing the YAML, run `.venv/bin/python scripts/curate_investigations.py`.

With Docker, use the existing Compose workflow. The API mounts `data/investigations` writable for explicit rebuilds; original recordings remain read-only. For offline review without Kafka/Flink:

```bash
.venv/bin/python -m uvicorn demo.api.app:app --host 127.0.0.1 --port 8000 --lifespan off
# In another terminal:
npm --prefix demo/web run dev -- --host 127.0.0.1
```

Open `http://localhost:3000` and choose Recording. `--lifespan off` skips streaming-consumer startup: Telemetry will correctly show unavailable stack services. Stop these local servers before starting Compose on the same ports.

## Audit results

The dated [audit results](dataset-audit-results.md) record seven admitted bags, 317,443 source messages, zero extraction errors and 96/96 reconciled previews. These are measurements from that preparation run, not promises about future downloads. [Scorecards](../examples/dataset_audit_results.json) and the [notebook](../examples/dataset_audit.ipynb) retain the evidence.

## Shared workbench

Select the recording once above all three tabs. Availability separates dataset support, prepared analysis and runtime services. Uploaded files can be replayed after validation; they do not automatically receive prepared investigation or localization evidence. See [behavior and design decisions](shared-dataset-workbench-plan.md).

## Evidence contract and validation

- Read-only endpoints: `/api/investigations`, `/{dataset_id}`, and `/{dataset_id}/interval?analysis_id=...&start_s=...&end_s=...`. Registered IDs only; source paths are not client inputs.
- Source identity, content digest, recipe signature and exact analysis ID are checked. Digest checks are cached by file stat identity, including ctime. Stale or changed evidence is rejected; publication is atomic per recording.
- JSON source nanoseconds are strings. Plots use relative seconds. Odometry twist is labeled with its child frame; unstamped command frames stay unspecified.
- Interval responses cap series at 60, time buckets at 240 per series, events at 200 with complete counts, and previews to prepared samples. Each bucket retains min/max/mean/count; empty buckets are not interpolated. The API caches 16 recent interval responses. Moving the cursor does not reread bags or fetch more evidence.
- Preview images are at most 256 pixels on the long edge. Mono16 display divides by 257; depth uses a fixed 0–5 m display scale. Scan previews retain at most 360 beams and label stride, source time and sensor frame. These are sampled views, not continuous playback or fused maps.
- Reviewed cases and nominal intervals use the same recorded-time axis independently of replay speed. This phase does not synchronize the offline cursor with a running replay.

Local validation: Python coverage tests, frontend interaction tests, production build, lint and Compose configuration. The Docker stack was started and all five readiness services reported ready; TUM VI Room 4 completed replay data was inspected in the browser. This does not replace CI's clean-stack replay/oracle/dropout smoke test. Named-volume inventory remains separate from the historical host audit.

## Rebuild evidence from the page

Select a registered, installed recording and click **Rebuild evidence**. The button starts background analysis, shows the current stage, and reloads results automatically on success. Reopening the page reconnects to a running job. Failures leave previous bundles intact and allow retry. There is no terminal step for this flow.

`POST /api/investigations/{dataset_id}/preparation` requires `X-Requested-With: ROS-Workbench` and starts a job (202); `GET` on the same path reports idle, running, completed, or failed. Repeated requests for the running recording reuse its job; another recording receives 409 until the worker is free. Unknown IDs return 404 and missing sources return 409. Reviewed cases are attached after analysis; an annotation failure is reported separately from successfully rebuilt evidence.

Analysis runs in a separate Python process so its parsing loops do not hold the API interpreter lock. An OS file lock serializes rebuilds; job status is stored on disk. Interrupted jobs are reported on the next status check and can be retried. Incomplete staging directories are cleaned after worker exit or when the next rebuild acquires the lock. The published bundle remains available until its replacement is complete. Each successful API rebuild keeps the current bundle and one previous version; older completed versions are removed.

Create `data/investigations` as your host user before starting Compose (`mkdir -p data/investigations`). When the API runs as root, the child uses that folder's UID/GID so Linux bind-mount files remain host-owned. Existing root-owned output may need a one-time ownership repair: `sudo chown -R "$(id -u):$(id -g)" data/investigations`. This does not change ownership of the API's other volumes.

Keep the default single API worker. The child shares the container's CPU and memory budget: process isolation removes interpreter-lock contention, but is not a resource quota or a durable job queue. If the API dies before recording completion, status reports an interrupted attempt even if publication finished; retry is safe. The CLI remains available for batch preparation; do not run it concurrently with a page rebuild.

## Recording tab wording

The tab opens with **Recording analysis** and a task instruction: select an incident or choose a time range to inspect signals and source samples. **Detected incidents** are grouped rule-based warnings, not confirmed failures. **Reviewed examples** are optional saved intervals with human-reviewed notes. **Signals and samples** identifies the shared time-range controls and plots.

Evidence status describes explanation support, not confidence in a cause: **Evidence available**, **Limited evidence**, or **Explanation unavailable**. Measurements, possible explanations, uncertainty, and next checks remain separate. Chart aggregation and source identifiers remain available under **How to read the plots** and **Analysis coverage and source details**.
