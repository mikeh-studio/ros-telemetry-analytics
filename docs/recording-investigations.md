# Recording investigations and dataset audit

Implemented from the [reviewed plan](dataset-evaluation-and-workbench-plan.md). Seven real recordings are prepared locally, including all four additions. The **Recording Investigation** tab works without a replay. It provides versioned evidence, interval selection, three aligned plots with a shared recorded-time cursor, bounded image/scan previews, event details, and topic coverage.

## Review now

Open ROS Workbench, choose **Recording Investigation**, then select:

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

With Docker, use the existing Compose workflow. The API now mounts `data/investigations` read-only. For offline review without Kafka/Flink:

```bash
.venv/bin/python -m uvicorn demo.api.app:app --host 127.0.0.1 --port 8000 --lifespan off
# In another terminal:
npm --prefix demo/web run dev -- --host 127.0.0.1
```

Open `http://localhost:3000` and choose Recording Investigation. `--lifespan off` skips streaming-consumer startup: Telemetry Health will correctly show unavailable stack services. Stop these local servers before starting Compose on the same ports.

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
