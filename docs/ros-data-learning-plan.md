Implementation follow-up: [recording investigations and completed host audit](recording-investigations.md). This document preserves the original planning baseline.

**ROS data research and learning plan — draft for review**

Prepared September 20, 2026. Repository inspected at `8668ab0`.

Selected next scope: current-dataset evaluation plus recommendations 1 and 2. See the [dataset evaluation and Workbench implementation plan](dataset-evaluation-and-workbench-plan.md) for the proposed work packages, curation decisions and completion criteria. The broader options below remain research context.

The recommended direction is to build a small collection of explainable failure investigations: what changed in the recording, which measurement exposed it, which alert was useful, and which view made the evidence understandable. Start with inexpensive additions to existing datasets, then add one dataset with a documented timing problem. Bring offline sensor evidence into ROS Workbench before adding many more detectors.

Suggested first scope: **LILocBench comparisons + TUM camera examples + a timing investigation using NTU VIRAL**. ARCO is the next choice for ROS 2 and radar/LiDAR work. Each phase below produces something independently reviewable.

This is research and an implementation proposal. Source pages and current code were inspected; new datasets were not downloaded, and ingestion, replay, and detector performance were not tested in this task. Published download sizes are approximate. A listed download is not a verified local import.

**1. What the project already supports**

| Area | Current implementation | Implication for this plan |
| --- | --- | --- |
| Recording formats | ROS 1 `.bag`, ROS 2 bag directories, standalone `.db3` and `.mcap` | Most shortlisted sensor recordings fit the reader; archives need extraction and custom types need inspection. |
| Offline timing | Rates, gaps, continuity, topic pairing and skew | Reuse these checks. Current relationship timing uses bag receive/log timestamps, so add a separate source-header view. |
| Offline payloads | Odometry, IMU, command response, TF, diagnostics, image features, LaserScan and PointCloud2 | Extend the existing analyzers; do not rebuild them under new names. |
| Point clouds | Counts, field names, empty clouds, byte completeness and presence of XYZ fields | Finite XYZ values, spatial coverage and geometric quality require additional decoding. `is_dense` is a publisher declaration, not verification. |
| Recorded replay | Publishes message timing and payload size | Uploading a bag does not currently bring its image-quality or scan-quality results into the mission view. This is a useful product gap. |
| Live observations | Selected payload attributes and sampled incident signals; transport and recovery experiments | Preserve this path, but distinguish live observations from offline analysis and replay metadata. |
| Localization | TUHH label-based evaluation and separate live Nav2 investigations | Keep these as existing evidence. Other sensor datasets do not automatically contain AMCL particles, estimator output, or failure labels. |
| Coverage | Explicit full/partial/failed/timing-only/no-message/disabled statuses | Show these per topic and per check. A readable message type does not establish complete semantic analysis. |

Evidence: [analysis guide](bag-analysis.md), [domain extraction](../src/ros_telemetry_analytics/domain.py), [domain analyzers](../src/ros_telemetry_analytics/domain_analysis.py), [recorded replayer](../demo/replayer/engine.py), and [current reliability scope](reliability-roadmap.md). Runtime results described in existing documents were not reproduced here.

Local file inspection found TUM RGB-D `freiburg1_xyz`, TUM VI `room4_512`, and LILocBench `dynamics_0`. OpenLORIS and ARCO have configuration entries but their configured archives are absent. The [dataset manifest](../configs/public_test_datasets.yaml) still marks LILocBench as pending updated-analyzer validation; file presence is not a new validation result.

**2. Download options, ranked by learning value for this project**

The learning goals and priorities below are recommendations inferred from dataset contents and the current implementation. They are not claims that a particular recording contains a confirmed robot failure.

| Priority and dataset | Concrete starting sample and download route | What it adds | Integration effort |
| --- | --- | --- | --- |
| **First: expand LILocBench** | Keep installed `dynamics_0`; add no-camera `static_0` (**141.8 MB**) and `lt_changes_0` (**103.8 MB**), plus their public ground truth. [Official downloads](https://www.ipb.uni-bonn.de/html/projects/localization_benchmark/) | Compare an unchanged environment, moving people, and rearranged objects using scans, commands and wheel odometry. | Low for batch analysis; new per-sequence catalog entries and a ground-truth adapter for comparisons. |
| **First: expand TUM RGB-D** | Add `freiburg3_sitting_xyz` and `freiburg3_walking_xyz`. The detailed download entries list approximately **0.72 GB and 0.49 GB** with ROS-bag links. Choose bags rather than PNG/TXT archives. [Official downloads](https://cvg.cit.tum.de/data/datasets/rgbd-dataset/download) | Compare slowly and quickly moving foreground objects; develop image-quality and context views using the existing image analyzer. | Low for batch analysis; image previews and feature tracking are new work. |
| **Best new dataset for timing: NTU VIRAL** | `eee_03`, **4.3 GB ZIP**, 181.4 seconds; extract its ROS recording. [Author download table](https://ntu-aris.github.io/ntu_viral_dataset/) | Authors document Ouster point-cloud/IMU timestamp jitter and provide a repair script. Multisensor data includes cameras, LiDAR, IMUs and UWB. | Medium: topic/clock profile, possible custom UWB definitions, and source-header timing analysis. |
| **Next for ROS 2: ARCO** | Existing planned `Trajectory 1`: about **1.2G ZIP** on the server index; repository notes about **3 GiB extracted DB3**. [Dataset description](https://robotics.upo.es/datasets/ArcoDataset/main.html), [file index](https://robotics.upo.es/datasets/ArcoDataset/bags/) | Native ROS 2, radar/LiDAR comparison, standard PointCloud2 and custom radar messages. | Low–medium for current checks; medium–high for radar semantics and spatial analysis. |
| **Next for service-robot scenes: OpenLORIS** | Existing planned café archive: **6.74 GB** per local manifest. Download through the author's current [download index](https://github.com/lifelong-robotic-vision/OpenLORIS-Scene/blob/master/download.md). | RGB-D, fisheye, separate accelerometer/gyro streams, wheel odometry and environmental variation. [Sensor and issue notes](https://lifelong-robotic-vision.github.io/dataset/scene.html) | Existing batch profile; larger storage/decompression cost and calibration interpretation. |
| **Later for difficult geometry: Hilti–Oxford 2022** | `exp14_basement_2.bag`, **6.26 GB**, or `exp18_corridor_lower_gallery_2.bag`, **8.66 GB**. [Author-hosted bag list](https://huggingface.co/datasets/Hilti-Research/hilti-slam-challenge-2022/tree/main/rosbags) | Camera/LiDAR/IMU behavior in basements and corridors; these two sequences have dense reference trajectories. [Dataset card](https://huggingface.co/datasets/Hilti-Research/hilti-slam-challenge-2022) | Medium for sensor QA; high for estimating geometric degeneracy or running a SLAM baseline. |
| **Later for a new problem family: UrbanNav** | `UrbanNav-HK-Tunnel-1`, published **17 GB / 398 seconds**, with separate GNSS and reference files. [Author download table](https://github.com/IPNL-POLYU/UrbanNavDataset) | GNSS availability and consistency through difficult urban settings; a reason to add GNSS analytics. | High: inspect actual GNSS schemas, add adapters, normalize coordinates and clock domains. |
| **Alternative visual-inertial benchmark: EuRoC MAV** | Start with an easy sequence, then a difficult one such as `MH_01_easy` / `MH_04_difficult`, after verifying archive contents. [Current ETH landing page](https://projects.asl.ethz.ch/datasets/euroc-mav/) | Stereo exposure differences, camera/IMU timing, and aggressive motion. | Low–medium if a bag is available; ASL-format extraction/conversion otherwise. Current downloads moved to ETH Research Collection; DOI access failed during this research, so individual-file access and sizes remain unverified. |

Important interpretation notes:

- **LILocBench:** choose the sequences with public ground truth. Scene category is context, not a timestamped failure label. Ground truth is expressed at `base_link`; compare other poses only after their frames are reconciled. [Dataset specification](https://www.ipb.uni-bonn.de/html/projects/localization_benchmark/)
- **NTU VIRAL:** preserve original files before trying the author's timestamp regularization. Ground truth is measured at a prism offset from the IMU; the authors call out a **0.4 m offset**. Comparing uncorrected frames could manufacture a localization error. [Author notes](https://ntu-aris.github.io/ntu_viral_dataset/)
- **OpenLORIS:** historical duplicate odometry and coordinate/calibration problems were fixed in earlier releases; do not assume current files retain those faults. A missing depth frame in `office1-6` is separately documented, making that an optional focused follow-up. The current index replaces obsolete Google Drive links with Hugging Face/Baidu. [Issue history](https://lifelong-robotic-vision.github.io/dataset/scene.html), [current index](https://github.com/lifelong-robotic-vision/OpenLORIS-Scene/blob/master/download.md)
- **ARCO:** the provided trajectory is a LiDAR-derived baseline, not independent motion-capture truth. Its radar motivation does not establish that these recordings contain adverse-weather failures. [Dataset description](https://robotics.upo.es/datasets/ArcoDataset/main.html)
- **EuRoC:** independent camera auto-exposure is documented, as are limitations in motion-reference synchronization and laser-tracker accuracy during dynamic motion. [Author caveats](https://projects.asl.ethz.ch/datasets/euroc-mav/)

Published dataset licenses should travel with the download manifest: TUM RGB-D is [CC BY 4.0 unless otherwise stated](https://cvg.cit.tum.de/data/datasets/rgbd-dataset); LILocBench and NTU VIRAL specify noncommercial share-alike terms on their linked pages; ARCO and Hilti specify CC BY-NC-SA 3.0; OpenLORIS specifies CC BY-ND 4.0. Keep raw bags and modified datasets local, record attribution, and check the exact release terms before sharing derived recordings. EuRoC and UrbanNav release terms still need to be captured for the selected files.

**3. Problems worth learning to recognize**

The alert rules in this table are proposed experiments. Thresholds need calibration on development recordings and evaluation on different recordings; they are not universal robot limits.

| Problem and observable evidence | Analytics / alert proposal | Useful visualization | Interpretation boundary |
| --- | --- | --- | --- |
| **Missing or irregular messages**: gaps, bursts, changing cadence | Existing gap/rate checks with topic-specific expected behavior; exclude startup, shutdown and intentionally sparse topics | Topic-by-time availability heatmap; interval histogram; existing rate history | A recording gap does not establish whether the sensor, network or recorder caused it. |
| **Messages arrive with misleading time**: repeats, backward stamps, abrupt offset changes | Compare source-header intervals with bag-log intervals; chart `log time − header time`; flag persistent shifts within a known clock segment | Two aligned interval plots, offset trend, and pairwise skew plot with unmatched counts | That difference includes clock offset and buffering; it is not automatically network latency. |
| **Camera publishes unusable or repeated frames** | Reuse intensity, sharpness, depth-validity and duplicate features; add persistence and motion context; optional feature-track survival | Small image filmstrip linked to sharpness/exposure/depth plots and incident intervals | A featureless wall can be sharp; a stationary scene can repeat. A dark image alone does not prove camera failure. |
| **LiDAR publishes incomplete or uninformative scans** | Reuse scan-validity/empty-cloud checks; add bounded XYZ sampling, finite-value fraction, occupied angular sectors and point-count change | Angle-by-time scan heatmap; coverage plot; selected scan/point-cloud snapshot | No-return beams can be normal in open space. Sparse geometry can impair localization with a functioning sensor. |
| **Commanded motion and observed motion disagree** | Extend command-response checks with valid timestamp/frame matching and persistence; compare full planar motion for holonomic robots | Commanded vs measured velocity, response delay, and trajectory colored by disagreement | Odometry is an estimate. Disagreement may reflect frame/timing errors, controller limits or wheel slip; it does not identify a cause. |
| **Localization becomes unreliable** | Compare short-window relative motion between compatible estimates; examine uncertainty and estimator status; score against separate reference poses when available | Equal-scale XY trajectory, position/heading residuals, uncertainty and event bands | Raw sensor bags often need an estimator run first. Ground truth is scoring evidence, never a detector input. |
| **Transforms are disconnected, stale or semantically wrong** | Extend TF connectivity/cycle checks with lookup availability at observation time, expected frame chains and reset-aware jump interpretation | Frame graph with age/status plus selected transform history | Static transforms do not need periodic publication. Map corrections can legitimately jump. |
| **IMU values are implausible or biased** | Finite checks, calibrated saturation limits, stationary-window bias estimates, axis/frame checks; later noise characterization | Per-axis acceleration/gyro plots; stationary-window distributions; optional frequency view | Gravity, acceleration and sensor orientation must be separated before treating a magnitude as a fault. |
| **GNSS loses availability or conflicts with other motion** | Later NavSatFix/custom-message support: fix state, covariance, position jumps and local-frame residuals; use satellite-quality fields only if present | Route colored by fix state plus aligned residual/covariance plots | Poor GNSS can still produce a fix. Raw RINEX requires separate processing; a bag may not expose all satellite diagnostics. |
| **The telemetry pipeline is falling behind** | Reuse live QoS, queue, retry, rejection and recovery evidence; add backlog-age and traffic-spike experiments | Publisher → gateway → broker → processor → UI timeline with counts and lag | A downloaded bag cannot reconstruct unrecorded DDS discovery or queue behavior. Use controlled live experiments. |

Two ROS semantics matter when designing these checks: `odom` is intended to remain continuous while `map` may jump during corrections; QoS incompatibility can prevent a publisher/subscriber pair from communicating. Frame-aware checks and direct middleware evidence avoid misleading alerts. [ROS REP-105](https://raw.githubusercontent.com/ros-infrastructure/rep/master/rep-0105.rst), [ROS 2 QoS documentation](https://docs.ros.org/en/humble/Concepts/Intermediate/About-Quality-of-Service-Settings.html)

Battery degradation, motor heating, actuator wear and task/planner failures are also useful future areas, but this shortlist does not establish suitable labeled examples. Add those only when a recording includes the required battery/current/temperature, joint effort, action status or controller diagnostics. Existing simulation is a better immediate source of controlled stuck-motion and TF faults than assuming a perception benchmark contains them.

**4. Suggested build order**

**Phase A — Establish a small comparison library. Effort: small.**

1. Analyze the installed LILocBench and TUM recordings with their existing profiles; inspect coverage and extraction failures before interpreting warnings.
2. Add the two no-camera LILocBench sequences and two TUM RGB-D sequences above. Incremental published data size is approximately **1.46 GB**, excluding reference files and outputs. Reserve roughly **5–10 GB free** as an initial planning allowance, then measure actual usage.
3. For each recording, save source/version, checksum, license reference, topic types, clock/frame notes, expected-rate provenance, analysis coverage and observed anomalies. Distinguish publisher-specified rates from rates inferred from the same recording.
4. Create a short investigation for one timing question, one camera question and one motion/scan question. An honest finding that a warning is normal is useful learning evidence.

Deliverable: a comparison table and three evidence-backed investigation notes. No requirement to force a failure finding in each bag.

Existing command shape, using an isolated output so one investigation does not reconcile away another's outputs:

```bash
.venv/bin/ros-telemetry analyze \
  --config configs/public_robotics/lilocbench.yaml \
  --input data/raw/public_datasets/lilocbench/dynamics_0.bag \
  --output data/bronze/investigations/lilocbench-dynamics-0
```

This command is provided for the next implementation phase and was not run during research. New TUM sequences need explicit topic profiles, including exclusion of reference-pose topics from operational health expectations.

**Phase B — Make offline evidence visible in mission review. Effort: medium.**

Add a recording-analysis view backed by existing Parquet/JSON outputs. Join it to replay using the recording fingerprint, analysis version, topic and recorded timestamp. Show the difference between offline analysis and currently replayed observations; future samples must not be presented as online predictions.

The first screen should combine:

- A shared recorded-time cursor and selectable incident interval.
- Topic availability/rate history and analysis-coverage labels.
- Two or three relevant plots: for example, scan-validity plus command/odometry, or sharpness plus depth validity.
- A bounded image or scan preview when available, with the evidence timestamp and frame.
- A compact explanation: observation, rule, duration, recovery, uncertainty and suggested next inspection.

Keep full-resolution evidence available for selected intervals. Overview downsampling should preserve extrema, gaps and incident boundaries; do not connect trajectories across missing data or coordinate frames. The existing one-sample-per-second live signal projection is context, not enough evidence for every short event.

Deliverable: select an incident and explain it from one screen. Verify that plotted values match stored evidence and that a cursor selects the correct recording interval at both 1× and 5× replay.

Implementation seams: [dataset catalog](../demo/common/datasets.py), [incident details](../demo/web/src/IncidentDetail.jsx), [topic history](../demo/web/src/TopicHistory.jsx), and an API adapter for existing analysis outputs.

**Phase C — Build a clock and synchronization investigation. Effort: medium.**

Download NTU VIRAL `eee_03` plus its calibration/reference information; reserve roughly **15–25 GB free** for the archive, extraction, outputs and an optional derived copy. This is a planning allowance, not measured storage.

Compute per-topic header monotonicity, repeated stamps, source/log interval distributions, offset changes, and compatible topic-pair timing. Separate clock segments and record unknown clock relationships. Pair IMU windows around camera exposure times rather than expecting one IMU sample per camera frame. Require bounded matches and retain unmatched observations.

Compare original timing with a separately identified author-repaired copy if practical. Add controlled header offsets, drift, repeated stamps and delivery delays as distinct experiments. Keep a mutation manifest listing exactly which messages/fields changed; preserve originals.

Deliverable: an investigation that explains whether an alert came from source timing, recorded delivery timing, or unresolved clock ambiguity. Use new fault parameters and another sequence for final validation after freezing the rule. The **4.3 GB** first sample is a pilot; allow a separate download budget for the held-out sequence.

**Phase D — Choose one domain expansion. Effort: medium to large.**

| Option | Concrete work | Evidence needed before expanding |
| --- | --- | --- |
| **Recommended: ARCO sensor coverage** | Run existing profile; expose custom-message coverage; decode finite XYZ and angular coverage; add selective radar status/detection adapters | Supported topics produce correct fields; custom topics remain explicitly limited; selected snapshots agree with source payloads. |
| OpenLORIS camera usability | Add café scene comparisons, RGB-D previews and persistence-aware quality warnings | Review benign scene changes; retain separate accel/gyro rates; preserve release provenance. |
| Hilti geometry and localization | Add selected cloud views and a bounded geometry proxy; optionally run one reproducible external estimator | Show association with measured estimator error before claiming a predictor of localization failure. Ground-truth coverage must be visible. |
| UrbanNav GNSS | Add GNSS extraction, coordinate/time conversion and fix/residual views | Validate time and spatial transformations against author examples; distinguish reference outage from receiver outage. |

UrbanNav explicitly documents GPS-to-ROS-time conversion and ENU reference conversion. Its example leap-second offset belongs to the stated recording dates; use date-aware conversion rather than a global hardcoded constant. [Author getting-started guide](https://raw.githubusercontent.com/IPNL-POLYU/UrbanNavDataset/master/docs/GETTING_STARTED.md)

**Phase E — Turn useful experiments into reliable alerts. Effort: medium per problem family.**

Keep three evidence sets: original real recordings for exploration, controlled modifications for known fault timing, and untouched recordings for transfer checks. Natural scene difficulty is not a failure label. Human-reviewed findings remain provisional unless an independent signal establishes failure.

Evaluate event recall, false alerts per reviewed nominal hour, onset delay, recovery delay, duplicate alerts and fraction of time in unknown state. Report denominators and per-sequence results; short clips cannot establish a stable hourly false-alarm rate. Score only where reference and observation coverage support the claim. Track alert delay in recorded event time separately from wall-clock processing delay.

Use explicit open/hold/recover behavior, hysteresis and warmup. Freeze rules before final validation. Include benign cases such as stationary images, sparse scenes, legitimate map corrections, static TF and separate IMU sampling rates. Aggregate related symptoms without hiding their individual evidence.

Proposed review gates: every controlled supported fault produces an explainable result; selected nominal controls produce no unexplained alerts; unsupported intervals remain unknown; replay speed does not change event-time conclusions; runtime/memory/storage costs are measured. These are development gates, not production reliability claims.

**5. Integration details to include in the estimate**

- **Dataset installation:** the current catalog recognizes only selected manifest entries. Its archive entries remain `needs_extraction`; it does not automatically select extracted children. Add a separate playable input path and per-sequence entries. For ROS 2, preserve the bag directory and metadata, especially when files are split; a single DB3 upload may not represent the whole recording.
- **Download tooling:** the current `download` CLI targets configured NVIDIA assets, and `validate-public-robotics` analyzes installed profiles. Neither is a general downloader for this shortlist. Add a small manifest-driven fetch/extract workflow only when implementing the chosen pack.
- **Validation meanings:** public-suite success currently means discovered inputs completed the pipeline. Add explicit topic coverage and evidence checks before describing a dataset as fully supported or an alert as correct.
- **Feature transport:** joining offline evidence to recording review is the smallest useful step. Extending replay/live envelopes and stream processing for new payload features is separate work requiring schema and runtime validation.
- **Reference poses:** implement source-specific adapters with clock, frame, unit, alignment and coverage metadata. A trajectory plot alone is not localization scoring; raw sensors plus ground truth still need an estimated trajectory to compare.
- **Large inputs:** the replayer currently materializes per-message metadata in memory. Measure load time and peak memory before choosing long, high-rate recordings. Start with one sequence, and preserve timestamps, calibration and static transforms if making derived clips.

**6. Decisions proposed for review**

| Decision | Recommendation | Why |
| --- | --- | --- |
| Immediate scope | Phases A and B | Broadens learning with about 1.46 GB of new data and makes existing analytics inspectable. |
| First genuinely new dataset family | NTU VIRAL in Phase C | Documented timing behavior gives a concrete investigation question. |
| Next sensor domain | ARCO | Builds on an existing ROS 2 profile and exposes clear PointCloud2/custom-type gaps. |
| Alert strategy | Explainable rules plus controlled experiments first | Easier to understand false alarms and missing evidence before considering learned anomaly models. |
| Visualization priority | Aligned timelines, a few relevant plots, and small sensor previews | Each view answers a diagnostic question and can be checked against source data. |
| Defer | Full-corpus downloads, general 3D SLAM reconstruction, fleet prediction and broad hardware-failure claims | Revisit after individual investigations demonstrate useful evidence and manageable cost. |

The next implementation brief can therefore be bounded to: **install the small comparison pack, produce three reviewed investigations, and expose their existing sensor evidence in ROS Workbench.** The subsequent timing and domain phases remain separate review decisions.
