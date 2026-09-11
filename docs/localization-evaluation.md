# Localization integrity evaluation

[Back to README](../README.md)

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
[sample evaluation](../examples/sample_localization_eval.md) and
[`configs/public_test_datasets.yaml`](../configs/public_test_datasets.yaml) for the
source manifest and exact thresholds.

## Measured follow-up

The [full study report](../examples/localization_study.md) and
[machine-readable experiment results](../examples/localization_study_results.json)
cover all 21 runs and 417,185 samples. Development selected a **0.36 m** spread
threshold with no heading signal or recovery hold. On the six evaluation runs,
macro sample recall increased from **0.362 to 0.455**, macro F1 from **0.518 to
0.589**, and macro event recall from **0.525 to 0.610**. Recall and F1 improved
on each of the six runs.

This is a tradeoff: macro precision fell from **0.924 to 0.857**, and false-alarm
events/hour rose from **27.4 to 40.2**. The development selection's five-point
precision-loss limit did not hold on the evaluation environments. Therefore
**the 0.40 m default stays unchanged**; 0.36 m is an opt-in candidate, not a
universally better detector. On the previously inspected warehouse run, recall
rose from 0.468 to 0.542 and detections from 16/24 to 17/24, while precision fell
from 0.856 to 0.760 and false alarms increased from three to five.

Reproduce the candidate on any complete run without overwriting the baseline:

```bash
.venv/bin/ros-telemetry evaluate-localization \
  --input /path/to/parquets/processed/rec_20250821_104113_id_01.processed.parquet \
  --input /path/to/parquets/processed/rec_20250821_104113_id_02.processed.parquet \
  --particle-spread-threshold-m 0.36 \
  --output data/evaluations/warehouse-recall-candidate
```

The [investigation notebook](../examples/localization_investigation.ipynb)
reproduces source-quality checks and explains the original eight unmatched
events: six had no alert coverage; two occurred during an alert already matched
to another event. Simply tuning uncertainty cannot eliminate confidently wrong
localization. A separate [live Nav2 experiment](live-ros2.md#controlled-nav2-localization-disturbance)
now tests relative AMCL/odometry motion disagreement after capture. That stationary
experiment does not extend this benchmark: evaluating independent motion or
scan/map evidence on these labeled runs remains future work.

## Compare detector changes on separate environments

The `study-localization` command loads all 42 processed members, verifies run
sample counts against the source metadata, and compares the unchanged baseline
with calibrated spread thresholds and causal recovery holds. Both members of a
run stay together. The frozen split in
[`configs/localization_study.json`](../configs/localization_study.json) uses 15
runs from five environments for development and reserves six runs from
`symmetric_exp_3` and `unsymmetric_exp_3` for evaluation. The previously inspected
warehouse run belongs to development.

Extract `parquets/processed/` from the upstream archive locally, then run:

```bash
.venv/bin/ros-telemetry study-localization \
  --input-dir /path/to/parquets/processed \
  --manifest configs/localization_study.json \
  --output data/evaluations/localization-study
```

The 21 candidate configurations combine spread thresholds of 0.20–0.50 m in
0.05 m steps with recovery holds of 0, 250, or 500 ms. The pose-jump threshold
stays at 0.5 m. Selection maximizes development macro sample F1, subject to
macro precision losing at most five percentage points and macro event recall
being at least the baseline. Each run receives equal weight in macro scores.
The baseline is always a candidate. `selection.json` records the decision
**before** the evaluation runs are loaded. Only the baseline and selected
configuration are scored on the held-out environments.

A recovery hold keeps an alert active for a specified time after the last
threshold crossing. It uses past and current observations only, never backfills
predictions, and resets at source-file and upstream segment boundaries. The
original evaluator defaults remain unchanged; a candidate can be reproduced
with `--particle-spread-threshold-m` and `--recovery-hold-ms`.

The follow-up manifest
[`configs/localization_heading_study.json`](../configs/localization_heading_study.json)
adds weighted circular particle-heading spread. Its final 18 configurations
combine position thresholds of 0.35–0.40 m in 0.01 m steps, no recovery hold, and
heading spread disabled or thresholded at 0.2 or 0.4 radians. The unchanged
baseline is included. This finer grid followed development-only coarse
comparisons: a 0.35 m threshold improved recall but lost more precision than the
guardrail allowed. The grid was refined without scoring alternative candidates
on the evaluation set.
Use that manifest with a separate output directory to reproduce the second
experiment. The split and selection guardrails are identical. Only the
baseline's evaluation performance had been inspected before this follow-up;
no alternative-candidate evaluation scores informed its selection.

Heading spread uses the particle weights and circular resultant length, so
headings close together across the −π/π boundary do not appear widely separated.
It is disabled by default and can be enabled in `evaluate-localization` with
`--heading-spread-threshold-rad`. Ground-truth heading is not an input. These
processed files do not contain an odometry measurement field; an odometry
disagreement feature would require extending the input adapter.

Outputs include `study.md`, `study.json`, `selection.json`, and one normalized
sample file per run. JSON contains source SHA-256 hashes, the split, the full
development candidate table, per-run scores, and per-event diagnostic evidence.
Downloads and generated outputs remain local and ignored by Git. The study
does not overwrite `data/evaluations/latest` or the Flight Deck's baseline.

## Interpret missed events and data quality

The one-to-one event score distinguishes individual incidents: one long alert
cannot claim multiple labeled events. Consequently an unmatched event is not
necessarily an interval without an alert. The diagnostics distinguish
`unmatched_with_alert_coverage` from `no_alert_coverage`, and expose the signal
maxima and alerted failure-sample counts for each event.

Record-level precision and recall retain the upstream repeated timestamps to
remain comparable to the published baseline. Separate duration metrics use the
last alert state at each unique timestamp until the next timestamp in that
segment. Conflicting labels at the same timestamp exclude that interval from
labeled duration metrics; the excluded duration is reported. The final sample
has no extrapolated duration, and intervals never bridge resets or file
boundaries. Declared and observed failure-label counts are reported separately
when the source CSV and processed Parquet disagree; the published Parquet labels
are the scoring authority.

Detection-delay percentiles apply only to matched events, with an already-active
alert assigned zero delay. Misses remain separate. False alarms/hour divides
unmatched alert events by all observed segment time, including failure time.
These brief, failure-rich simulations cannot establish a real-world alarm rate.
Upstream segment boundaries encode localization resets; continuous operation
without those boundaries requires its own evaluation.

### Retained study evidence

`examples/localization_study_results.json` is the compact, inspectable result of
this published study, including source hashes, candidate scores, and per-run evidence. It is
versioned intentionally so the published aggregate results remain inspectable
without downloading the source corpus or relying on expiring CI artifacts.
The notebook and full per-event diagnostics still require the locally generated
study outputs.
Raw samples and routine generated experiment directories remain outside Git.
Candidate F1 ties prefer shorter hold, higher spread threshold, then heading
disabled, followed by manifest order; the held-out data never breaks ties.
