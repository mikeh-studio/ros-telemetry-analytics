# Localization detector study

**Decision:** retain the 0.40 m default; make the 0.36 m candidate opt-in. The candidate improves recall and F1 on all six held-out runs, but evaluation macro precision falls by 6.7 percentage points and false alarms increase. The five-point precision constraint was a development selection rule, not a guarantee on unseen environments.

Published TUHH simulation data; a fixed split by environment. The evaluation environments were excluded from candidate selection.

Selected spread threshold: **0.36 m**; recovery hold: **0 ms**. AMCL pose-jump threshold remains 0.5 m.
Particle heading-spread threshold: disabled.
Development-only refinement after coarse threshold/hold and heading grids retained the baseline. The coarse 0.35 m candidate improved recall but exceeded the five-point precision-loss limit, motivating a finer 0.35-0.40 m grid. Same frozen environment split. Only baseline evaluation performance was inspected before refinement; no alternative-candidate evaluation scores informed selection.

## Baseline versus selected detector

Precision, recall, F1, and event recall below are macro averages across runs. Duration coverage and false alarms/hour pool time across runs.

| Split | Detector | Runs | Precision | Recall | F1 | Event recall | Failure time covered | False alarms/h |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| development | baseline | 15 | 0.728 | 0.543 | 0.549 | 0.614 | 0.602 | 59.800 |
| development | selected | 15 | 0.680 | 0.616 | 0.576 | 0.673 | 0.676 | 51.257 |
| evaluation | baseline | 6 | 0.924 | 0.362 | 0.518 | 0.525 | 0.357 | 27.385 |
| evaluation | selected | 6 | 0.857 | 0.455 | 0.589 | 0.610 | 0.450 | 40.165 |

## Development candidates

Eligibility uses the fixed precision and event-recall guardrails, before ranking by F1.

| Spread (m) | Hold (ms) | Heading (rad) | Precision | Recall | F1 | Event recall | Eligible |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | --- |
| 0.4 | 0 | off | 0.728 | 0.543 | 0.549 | 0.614 | yes |
| 0.35 | 0 | off | 0.658 | 0.640 | 0.584 | 0.687 | no |
| 0.35 | 0 | 0.2 | 0.598 | 0.644 | 0.551 | 0.669 | no |
| 0.35 | 0 | 0.4 | 0.658 | 0.640 | 0.584 | 0.687 | no |
| 0.36 | 0 | off | 0.680 | 0.616 | 0.576 | 0.673 | yes |
| 0.36 | 0 | 0.2 | 0.615 | 0.622 | 0.542 | 0.656 | no |
| 0.36 | 0 | 0.4 | 0.680 | 0.616 | 0.576 | 0.673 | yes |
| 0.37 | 0 | off | 0.694 | 0.593 | 0.566 | 0.648 | yes |
| 0.37 | 0 | 0.2 | 0.624 | 0.601 | 0.532 | 0.633 | no |
| 0.37 | 0 | 0.4 | 0.694 | 0.593 | 0.566 | 0.648 | yes |
| 0.38 | 0 | off | 0.707 | 0.575 | 0.560 | 0.640 | yes |
| 0.38 | 0 | 0.2 | 0.633 | 0.586 | 0.526 | 0.625 | no |
| 0.38 | 0 | 0.4 | 0.707 | 0.575 | 0.560 | 0.640 | yes |
| 0.39 | 0 | off | 0.715 | 0.559 | 0.554 | 0.632 | yes |
| 0.39 | 0 | 0.2 | 0.638 | 0.574 | 0.521 | 0.617 | no |
| 0.39 | 0 | 0.4 | 0.715 | 0.559 | 0.554 | 0.632 | yes |
| 0.4 | 0 | 0.2 | 0.647 | 0.561 | 0.516 | 0.602 | no |
| 0.4 | 0 | 0.4 | 0.728 | 0.543 | 0.549 | 0.614 | yes |

## Per-run results

| Run | Environment | Split | Detector | Precision | Recall | Event recall | False alarms | P95 delay (ms) |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| rec_20250821_104113 | warehouse | development | baseline | 0.856 | 0.468 | 0.667 | 3 | 2025.000 |
| rec_20250821_104113 | warehouse | development | selected | 0.760 | 0.542 | 0.708 | 5 | 2760.000 |
| rec_20250828_102407 | warehouse | development | baseline | 0.992 | 0.306 | 0.393 | 0 | 3700.000 |
| rec_20250828_102407 | warehouse | development | selected | 0.949 | 0.383 | 0.536 | 1 | 2750.000 |
| rec_20250827_161251 | warehouse | development | baseline | 0.994 | 0.427 | 0.636 | 1 | 4000.000 |
| rec_20250827_161251 | warehouse | development | selected | 0.993 | 0.517 | 0.667 | 2 | 3575.000 |
| rec_20250821_151429 | symmetric_exp_1 | development | baseline | 0.911 | 0.287 | 0.467 | 1 | 4500.000 |
| rec_20250821_151429 | symmetric_exp_1 | development | selected | 0.868 | 0.352 | 0.667 | 1 | 3525.000 |
| rec_20250821_141846 | symmetric_exp_1 | development | baseline | 0.994 | 0.424 | 0.385 | 1 | 3560.000 |
| rec_20250821_141846 | symmetric_exp_1 | development | selected | 0.891 | 0.518 | 0.615 | 2 | 2995.000 |
| rec_20250821_132354 | symmetric_exp_1 | development | baseline | 0.544 | 0.332 | 0.444 | 3 | 3150.000 |
| rec_20250821_132354 | symmetric_exp_1 | development | selected | 0.460 | 0.409 | 0.556 | 3 | 4230.000 |
| rec_20250822_132819 | symmetric_exp_2 | development | baseline | 0.347 | 0.826 | 0.679 | 15 | 2238.333 |
| rec_20250822_132819 | symmetric_exp_2 | development | selected | 0.315 | 0.894 | 0.643 | 8 | 749.167 |
| rec_20250822_135308 | symmetric_exp_2 | development | baseline | 0.625 | 0.710 | 0.879 | 5 | 3676.667 |
| rec_20250822_135308 | symmetric_exp_2 | development | selected | 0.588 | 0.803 | 0.939 | 4 | 1983.333 |
| rec_20250822_123916 | symmetric_exp_2 | development | baseline | 0.992 | 0.391 | 0.500 | 0 | 1960.000 |
| rec_20250822_123916 | symmetric_exp_2 | development | selected | 0.927 | 0.407 | 0.500 | 2 | 1810.000 |
| rec_20250828_105714 | symmetric_exp_3 | evaluation | baseline | 0.977 | 0.326 | 0.412 | 2 | 2405.000 |
| rec_20250828_105714 | symmetric_exp_3 | evaluation | selected | 0.905 | 0.405 | 0.529 | 8 | 3640.833 |
| rec_20250828_161448 | symmetric_exp_3 | evaluation | baseline | 0.932 | 0.278 | 0.500 | 0 | 2720.000 |
| rec_20250828_161448 | symmetric_exp_3 | evaluation | selected | 0.910 | 0.360 | 0.579 | 1 | 6879.167 |
| rec_20250825_100748 | symmetric_exp_3 | evaluation | baseline | 0.911 | 0.396 | 0.565 | 0 | 3460.000 |
| rec_20250825_100748 | symmetric_exp_3 | evaluation | selected | 0.893 | 0.437 | 0.609 | 1 | 3615.000 |
| rec_20250825_133605 | unsymmetric_exp_1 | development | baseline | 0.381 | 0.907 | 0.706 | 5 | 1411.667 |
| rec_20250825_133605 | unsymmetric_exp_1 | development | selected | 0.357 | 0.934 | 0.647 | 6 | 1140.000 |
| rec_20250825_135829 | unsymmetric_exp_1 | development | baseline | 0.505 | 0.791 | 0.765 | 16 | 983.333 |
| rec_20250825_135829 | unsymmetric_exp_1 | development | selected | 0.466 | 0.910 | 0.765 | 11 | 641.667 |
| rec_20250829_104641 | unsymmetric_exp_1 | development | baseline | 0.888 | 0.482 | 0.654 | 1 | 3080.000 |
| rec_20250829_104641 | unsymmetric_exp_1 | development | selected | 0.843 | 0.530 | 0.769 | 0 | 2505.000 |
| rec_20250825_161940 | unsymmetric_exp_2 | development | baseline | 0.388 | 0.749 | 0.767 | 5 | 1995.000 |
| rec_20250825_161940 | unsymmetric_exp_2 | development | selected | 0.387 | 0.862 | 0.733 | 2 | 1789.167 |
| rec_20250825_145941 | unsymmetric_exp_2 | development | baseline | 0.979 | 0.355 | 0.364 | 1 | 2955.000 |
| rec_20250825_145941 | unsymmetric_exp_2 | development | selected | 0.902 | 0.406 | 0.455 | 1 | 2800.000 |
| rec_20250825_153216 | unsymmetric_exp_2 | development | baseline | 0.521 | 0.694 | 0.902 | 6 | 2276.667 |
| rec_20250825_153216 | unsymmetric_exp_2 | development | selected | 0.496 | 0.779 | 0.902 | 6 | 1683.333 |
| rec_20250826_104543 | unsymmetric_exp_3 | evaluation | baseline | 0.896 | 0.415 | 0.567 | 6 | 2780.000 |
| rec_20250826_104543 | unsymmetric_exp_3 | evaluation | selected | 0.766 | 0.546 | 0.700 | 7 | 3100.000 |
| rec_20250826_095810 | unsymmetric_exp_3 | evaluation | baseline | 0.907 | 0.367 | 0.483 | 4 | 5045.000 |
| rec_20250826_095810 | unsymmetric_exp_3 | evaluation | selected | 0.843 | 0.474 | 0.621 | 5 | 3345.000 |
| rec_20250826_102611 | unsymmetric_exp_3 | evaluation | baseline | 0.923 | 0.392 | 0.625 | 3 | 3010.000 |
| rec_20250826_102611 | unsymmetric_exp_3 | evaluation | selected | 0.828 | 0.508 | 0.625 | 0 | 2530.000 |

## Original warehouse baseline: unmatched events

One-to-one event matching is unchanged. An unmatched event can still have alert coverage when a long alert has already been assigned to another event.

| Event | Classification | Failure samples alerted | Max spread (m) | Max jump (m) |
| --- | --- | ---: | ---: | ---: |
| rec_20250821_104113:expected:5 | unmatched_with_alert_coverage | 247/247 | 0.543 | 0.130 |
| rec_20250821_104113:expected:6 | unmatched_with_alert_coverage | 52/52 | 0.452 | 0.091 |
| rec_20250821_104113:expected:8 | no_alert_coverage | 0/110 | 0.300 | 0.099 |
| rec_20250821_104113:expected:10 | no_alert_coverage | 0/608 | 0.348 | 0.118 |
| rec_20250821_104113:expected:19 | no_alert_coverage | 0/83 | 0.304 | 0.097 |
| rec_20250821_104113:expected:21 | no_alert_coverage | 0/152 | 0.265 | 0.108 |
| rec_20250821_104113:expected:23 | no_alert_coverage | 0/159 | 0.293 | 0.099 |
| rec_20250821_104113:expected:24 | no_alert_coverage | 0/466 | 0.374 | 0.111 |

## Methodology and limits

- Selection maximizes development macro sample F1 with precision at least baseline minus 0.05 and event recall at least baseline. Only the baseline and selected configuration are evaluated on the held-out environments.
- Original record-level scores retain repeated timestamps. Duration metrics use the final alert at each unique timestamp until the next timestamp within that source segment. Intervals with conflicting labels are excluded from labeled duration metrics; their duration and counts are reported in JSON.
- Detection-delay percentiles include matched events only; already-active alerts have zero delay. Misses are reported separately, not assigned zero delay.
- False alarms/hour uses observed segment time, including failure time. These short, failure-rich simulation runs do not establish a real-world alarm rate.
- Source segments end at upstream localization resets. The detector resets its hold at those boundaries and source-file boundaries; continuous-operation generalization requires a separate live evaluation.
- No ground-truth pose, error, or label is used in detector decisions. This experiment calibrates existing observable signals; it does not establish causes of failures or production readiness.
- See study.json for per-event evidence, data-quality counts, source hashes, the complete development candidate table, and the frozen split.

Source: https://doi.org/10.15480/882.15836 (CC BY 4.0).

## Source quality checks

Repeated-timestamp extra records: **112435**. Conflicting-label timestamp groups: **495**. Records missing both baseline signals: **0**.

All source sample totals must match the manifest. Failure-label count differences below compare published Parquet labels with the upstream info.csv; Parquet labels are used for scoring.

| Run | CSV failure samples | Parquet failure samples | Difference |
| --- | ---: | ---: | ---: |
| rec_20250821_132354 | 2776 | 2778 | +2 |
| rec_20250822_135308 | 8275 | 8271 | -4 |
| rec_20250828_105714 | 4860 | 4861 | +1 |
| rec_20250828_161448 | 6182 | 6183 | +1 |
| rec_20250825_135829 | 7306 | 7309 | +3 |
| rec_20250829_104641 | 3790 | 3789 | -1 |
| rec_20250825_161940 | 6513 | 6511 | -2 |
| rec_20250825_153216 | 8505 | 8500 | -5 |
