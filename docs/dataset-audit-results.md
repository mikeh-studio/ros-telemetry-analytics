# Dataset audit results

Historical host audit, 2026-09-21 UTC. Raw files and local artifact pointers are not included in Git.

## Audit outcome, 2026-09-21 UTC

The host inventory after cleanup contains **77 physical files and 12 logical bags** under the audited raw/demo/upload roots, totaling **10,596,815,779 bytes**. No host upload bags or generated host demo bag were present. Docker was stopped, so its named demo/upload volumes were not enumerated. This is a host inventory, not a claim that no additional recordings exist in volumes or other unconfigured locations.

All seven active recordings have **317,443 source messages**, zero extraction errors, and **96/96 reconciled previews**. Coverage is explicitly partial by message type: camera calibration/marker topics and LILocBench joint states remain timing-only. “Ready” means the evidence bundle is usable for its stated purpose, not that every signal is healthy or every type is decoded.

| Recording | Seconds | Messages | Checked previews | Admission / distinct use |
| --- | ---: | ---: | ---: | --- |
| TUM RGB-D Freiburg 1 XYZ | 30.429 | 25,626 | 12 | Keep active: candidate RGB/depth control; not certified fault-free |
| TUM VI Room 4 | 111.405 | 39,743 | 18 | Keep active: image usefulness and reference coverage |
| LILocBench Dynamics 0 | 159.978 | 30,577 | 18 | Keep active: scan and command/odometry observations |
| LILocBench Static 0 | 598.794 | 110,812 | 12 | Admit: static-environment comparison |
| LILocBench Changed environment | 435.989 | 85,117 | 12 | Admit: changed-scene comparison without failure labels |
| TUM RGB-D Sitting XYZ | 42.797 | 15,227 | 12 | Admit: slower foreground-motion comparison |
| TUM RGB-D Walking XYZ | 29.067 | 10,341 | 12 | Admit: faster foreground-motion comparison |

The four new bags occupy **1,669,265,823 bytes**, plus small reference files. Latest retained bundles total approximately **18.7 MB**. Their analysis times sum to about **343 s**; this is a sum across retained preparation runs. The measured full-pack process high-water memory was **449 MB**. Compressed RGB-D bags dominate runtime. Previous preparation versions and existing evaluation outputs were preserved, so total derived storage exceeds the latest-bundle figure.

Machine-readable scorecards, coverage, timing/header checks, reference checks, and cleanup receipts: [dataset_audit_results.json](../examples/dataset_audit_results.json). Full physical inventory and per-segment TUHH checks are in `data/evaluations/dataset-audit/<audit-id>/inventory.json`; the local `latest.json` resolves the current audit. The [executed notebook](../examples/dataset_audit.ipynb) reproduces count reconciliation and independently computes selected image intensity and scan-validity values from raw source messages.

## Findings that change interpretation

| Finding | Impact / confidence | Action and remaining uncertainty |
| --- | --- | --- |
| TUM VI image `frame_id` is exposure nanoseconds | High confidence; documented source convention | Group image scalar histories by topic and label the field honestly. Do not interpret changing exposure values as coordinate-frame changes. |
| LILocBench command stream lacks a documented periodic-rate contract | High confidence about the unsupported assumption; delivery cause unknown | Remove the assumed 43 Hz command rate in the investigation-only profile. Dynamics goes from 2,475 combined events to 3: two command/odometry observations and one odometry gap. Existing general-purpose profile stays available for comparison. |
| TUM VI reference gaps occur while camera/IMU delivery continues | High confidence for recorded intervals | Label reference context and evaluation limits. No camera/IMU outage claim. |
| Image darkness/sharpness depends on view, exposure and texture | Reviewed thumbnails corroborate a content change; physical cause unresolved | Keep as an investigation cue, not a malfunction label or validated estimator-failure detector. |
| TUHH has repeated times and conflicting labels | High confidence from fresh nested-field profiling | Preserve original source-file/segment boundaries and existing study conflict handling. Never resolve conflicts by silently dropping duplicates. |
| Three legacy reader fixtures are rejected by this reader | High confidence, reproduced | Keep as optional parser regression cases, not robot incidents. The fourth fixture's index is readable; exhaustive compressed-payload validation was not repeated. |

TUM VI's exposure convention and its special IMU metadata are documented in the [dataset paper, format section](https://cvg.cit.tum.de/_media/spezial/bib/schubert2018vidataset.pdf). No interpretation of IMU orientation/covariance as ordinary calibrated orientation is introduced here.

The three downloaded LILocBench references contain 3,194 / 11,929 / 8,700 poses. All checked pose values are finite, timestamps increase, and their numerical time spans cover almost all the corresponding recordings. Maximum gaps are about 150 ms. Coordinate/extrinsic alignment remains unvalidated, so they are retained for future evaluation and are not detector inputs.

TUHH's 42 processed parts contain **208 outer segment rows but 417,185 nested measurements**. The fresh label audit finds 96,310 failure labels, zero missing labels, 112,435 repeated-timestamp rows within segments, 495 conflicting-label timestamp groups, and no backward timestamps within those segments. The source summary reports 96,315 failure samples, five more than the stored processed labels; this existing discrepancy remains visible in the [localization study](../examples/localization_study.md). No split, label, or threshold was changed.

Freiburg 1 XYZ still has a topic-level `/tf` continuity warning: its maximum recorded gap is 51.327 ms, 7.164 times the mean interval. This is shown separately from the bounded anomaly-event list. A mixed TF stream has no single periodic contract; this ratio alone cannot establish a missing required transform. Retain it as a candidate control, and check transform-pair coverage before using it as a localization reference.

## Collection decisions and cleanup

- **Warehouse Run 17:** keep as a controlled timing demo. Its catalog description now discloses repeated payloads, zero header stamps and the constant 1×1 image. It is excluded from sensor-quality claims. The replay catalog defaults to an admitted real recording when available and otherwise keeps the demo fallback.
- **TUHH:** keep for simulation-based localization evaluation in its existing workflow.
- **NVIDIA visual-SLAM quickstart:** keep the canonical ROS 2 compatibility sample and archive. Reader metadata checks pass; approximately two seconds is inadequate for sustained-fault studies. Payload completeness was not certified in this audit.
- **Legacy fixtures:** keep four small targeted parser/index regressions. Optional tests skip if the local public fixtures are absent.
- **OpenLORIS, ARCO and nvblox:** defer. Hide the unavailable heavy recordings from the main replay selector; preserve source/configuration metadata.
- **Unique uploads, existing studies and failed-experiment evidence:** preserve. Named-volume inventory remains pending Docker availability.

Removed only these freshly rehashed, byte-identical cache files:

```text
data/raw/downloads/visual_slam/isaac_ros_visual_slam/quickstart_bag/quickstart_bag_0.db3
data/raw/downloads/visual_slam/isaac_ros_visual_slam/quickstart_bag/metadata.yaml
```

Their counterparts remain under `data/raw/isaac_ros_assets/visual_slam/isaac_ros_visual_slam/quickstart_bag/`, and `data/raw/downloads/visual_slam/quickstart.tar.gz` remains available. The asset loader uses the canonical extraction directory; no code/config dependency on the deleted cache extraction was found. The matching metadata was removed with its bag to avoid leaving an incomplete logical source. **1,660,798,923 logical bytes removed**; filesystem space recovery may differ. Tiny duplicate interface-spec files were retained. `scripts/cleanup_dataset_cache.py` defaults to a review receipt and applies only these exact verified matches when given `--apply`.
