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

## Unmatched events across all runs

One-to-one event matching is unchanged. An unmatched event can still have alert coverage when a long alert has already been assigned to another event. Both baseline and selected detectors are shown for every run with misses.

| Run | Split | Detector | Event | Classification | Failure samples alerted | Max spread (m) | Max jump (m) |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| rec_20250821_104113 | development | baseline | rec_20250821_104113:expected:5 | unmatched_with_alert_coverage | 247/247 | 0.543 | 0.130 |
| rec_20250821_104113 | development | baseline | rec_20250821_104113:expected:6 | unmatched_with_alert_coverage | 52/52 | 0.452 | 0.091 |
| rec_20250821_104113 | development | baseline | rec_20250821_104113:expected:8 | no_alert_coverage | 0/110 | 0.300 | 0.099 |
| rec_20250821_104113 | development | baseline | rec_20250821_104113:expected:10 | no_alert_coverage | 0/608 | 0.348 | 0.118 |
| rec_20250821_104113 | development | baseline | rec_20250821_104113:expected:19 | no_alert_coverage | 0/83 | 0.304 | 0.097 |
| rec_20250821_104113 | development | baseline | rec_20250821_104113:expected:21 | no_alert_coverage | 0/152 | 0.265 | 0.108 |
| rec_20250821_104113 | development | baseline | rec_20250821_104113:expected:23 | no_alert_coverage | 0/159 | 0.293 | 0.099 |
| rec_20250821_104113 | development | baseline | rec_20250821_104113:expected:24 | no_alert_coverage | 0/466 | 0.374 | 0.111 |
| rec_20250821_104113 | development | selected | rec_20250821_104113:expected:5 | unmatched_with_alert_coverage | 247/247 | 0.543 | 0.130 |
| rec_20250821_104113 | development | selected | rec_20250821_104113:expected:6 | unmatched_with_alert_coverage | 52/52 | 0.452 | 0.091 |
| rec_20250821_104113 | development | selected | rec_20250821_104113:expected:8 | no_alert_coverage | 0/110 | 0.300 | 0.099 |
| rec_20250821_104113 | development | selected | rec_20250821_104113:expected:10 | no_alert_coverage | 0/608 | 0.348 | 0.118 |
| rec_20250821_104113 | development | selected | rec_20250821_104113:expected:19 | no_alert_coverage | 0/83 | 0.304 | 0.097 |
| rec_20250821_104113 | development | selected | rec_20250821_104113:expected:21 | no_alert_coverage | 0/152 | 0.265 | 0.108 |
| rec_20250821_104113 | development | selected | rec_20250821_104113:expected:23 | no_alert_coverage | 0/159 | 0.293 | 0.099 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:2 | no_alert_coverage | 0/37 | 0.331 | 0.072 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:3 | no_alert_coverage | 0/27 | 0.305 | 0.082 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:4 | no_alert_coverage | 0/15 | 0.363 | 0.082 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:5 | no_alert_coverage | 0/194 | 0.379 | 0.103 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:10 | no_alert_coverage | 0/184 | 0.245 | 0.063 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:12 | no_alert_coverage | 0/27 | 0.316 | 0.093 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:13 | no_alert_coverage | 0/132 | 0.268 | 0.081 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:15 | no_alert_coverage | 0/96 | 0.360 | 0.089 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:17 | no_alert_coverage | 0/70 | 0.261 | 0.106 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:21 | no_alert_coverage | 0/441 | 0.360 | 0.103 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:22 | no_alert_coverage | 0/131 | 0.353 | 0.109 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:23 | no_alert_coverage | 0/3 | 0.293 | 0.000 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:24 | no_alert_coverage | 0/3 | 0.266 | 0.000 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:25 | no_alert_coverage | 0/2 | 0.235 | 0.000 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:26 | no_alert_coverage | 0/36 | 0.220 | 0.046 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:27 | no_alert_coverage | 0/123 | 0.392 | 0.111 |
| rec_20250828_102407 | development | baseline | rec_20250828_102407:expected:28 | no_alert_coverage | 0/32 | 0.293 | 0.072 |
| rec_20250828_102407 | development | selected | rec_20250828_102407:expected:2 | no_alert_coverage | 0/37 | 0.331 | 0.072 |
| rec_20250828_102407 | development | selected | rec_20250828_102407:expected:3 | no_alert_coverage | 0/27 | 0.305 | 0.082 |
| rec_20250828_102407 | development | selected | rec_20250828_102407:expected:10 | no_alert_coverage | 0/184 | 0.245 | 0.063 |
| rec_20250828_102407 | development | selected | rec_20250828_102407:expected:12 | no_alert_coverage | 0/27 | 0.316 | 0.093 |
| rec_20250828_102407 | development | selected | rec_20250828_102407:expected:13 | no_alert_coverage | 0/132 | 0.268 | 0.081 |
| rec_20250828_102407 | development | selected | rec_20250828_102407:expected:17 | no_alert_coverage | 0/70 | 0.261 | 0.106 |
| rec_20250828_102407 | development | selected | rec_20250828_102407:expected:21 | no_alert_coverage | 0/441 | 0.360 | 0.103 |
| rec_20250828_102407 | development | selected | rec_20250828_102407:expected:22 | no_alert_coverage | 0/131 | 0.353 | 0.109 |
| rec_20250828_102407 | development | selected | rec_20250828_102407:expected:23 | no_alert_coverage | 0/3 | 0.293 | 0.000 |
| rec_20250828_102407 | development | selected | rec_20250828_102407:expected:24 | no_alert_coverage | 0/3 | 0.266 | 0.000 |
| rec_20250828_102407 | development | selected | rec_20250828_102407:expected:25 | no_alert_coverage | 0/2 | 0.235 | 0.000 |
| rec_20250828_102407 | development | selected | rec_20250828_102407:expected:26 | no_alert_coverage | 0/36 | 0.220 | 0.046 |
| rec_20250828_102407 | development | selected | rec_20250828_102407:expected:28 | no_alert_coverage | 0/32 | 0.293 | 0.072 |
| rec_20250827_161251 | development | baseline | rec_20250827_161251:expected:6 | no_alert_coverage | 0/119 | 0.259 | 0.083 |
| rec_20250827_161251 | development | baseline | rec_20250827_161251:expected:8 | no_alert_coverage | 0/88 | 0.272 | 0.092 |
| rec_20250827_161251 | development | baseline | rec_20250827_161251:expected:10 | no_alert_coverage | 0/198 | 0.334 | 0.081 |
| rec_20250827_161251 | development | baseline | rec_20250827_161251:expected:13 | no_alert_coverage | 0/133 | 0.353 | 0.083 |
| rec_20250827_161251 | development | baseline | rec_20250827_161251:expected:17 | no_alert_coverage | 0/96 | 0.302 | 0.084 |
| rec_20250827_161251 | development | baseline | rec_20250827_161251:expected:19 | no_alert_coverage | 0/278 | 0.370 | 0.095 |
| rec_20250827_161251 | development | baseline | rec_20250827_161251:expected:21 | no_alert_coverage | 0/2 | 0.286 | 0.035 |
| rec_20250827_161251 | development | baseline | rec_20250827_161251:expected:22 | no_alert_coverage | 0/114 | 0.358 | 0.093 |
| rec_20250827_161251 | development | baseline | rec_20250827_161251:expected:23 | no_alert_coverage | 0/12 | 0.300 | 0.123 |
| rec_20250827_161251 | development | baseline | rec_20250827_161251:expected:24 | no_alert_coverage | 0/85 | 0.277 | 0.106 |
| rec_20250827_161251 | development | baseline | rec_20250827_161251:expected:27 | no_alert_coverage | 0/192 | 0.285 | 0.116 |
| rec_20250827_161251 | development | baseline | rec_20250827_161251:expected:29 | no_alert_coverage | 0/194 | 0.293 | 0.078 |
| rec_20250827_161251 | development | selected | rec_20250827_161251:expected:6 | no_alert_coverage | 0/119 | 0.259 | 0.083 |
| rec_20250827_161251 | development | selected | rec_20250827_161251:expected:8 | no_alert_coverage | 0/88 | 0.272 | 0.092 |
| rec_20250827_161251 | development | selected | rec_20250827_161251:expected:10 | no_alert_coverage | 0/198 | 0.334 | 0.081 |
| rec_20250827_161251 | development | selected | rec_20250827_161251:expected:13 | no_alert_coverage | 0/133 | 0.353 | 0.083 |
| rec_20250827_161251 | development | selected | rec_20250827_161251:expected:17 | no_alert_coverage | 0/96 | 0.302 | 0.084 |
| rec_20250827_161251 | development | selected | rec_20250827_161251:expected:21 | no_alert_coverage | 0/2 | 0.286 | 0.035 |
| rec_20250827_161251 | development | selected | rec_20250827_161251:expected:22 | no_alert_coverage | 0/114 | 0.358 | 0.093 |
| rec_20250827_161251 | development | selected | rec_20250827_161251:expected:23 | no_alert_coverage | 0/12 | 0.300 | 0.123 |
| rec_20250827_161251 | development | selected | rec_20250827_161251:expected:24 | no_alert_coverage | 0/85 | 0.277 | 0.106 |
| rec_20250827_161251 | development | selected | rec_20250827_161251:expected:27 | no_alert_coverage | 0/192 | 0.285 | 0.116 |
| rec_20250827_161251 | development | selected | rec_20250827_161251:expected:29 | no_alert_coverage | 0/194 | 0.293 | 0.078 |
| rec_20250821_151429 | development | baseline | rec_20250821_151429:expected:3 | no_alert_coverage | 0/39 | 0.285 | 0.074 |
| rec_20250821_151429 | development | baseline | rec_20250821_151429:expected:4 | no_alert_coverage | 0/143 | 0.281 | 0.091 |
| rec_20250821_151429 | development | baseline | rec_20250821_151429:expected:6 | no_alert_coverage | 0/145 | 0.211 | 0.095 |
| rec_20250821_151429 | development | baseline | rec_20250821_151429:expected:8 | no_alert_coverage | 0/83 | 0.385 | 0.094 |
| rec_20250821_151429 | development | baseline | rec_20250821_151429:expected:12 | no_alert_coverage | 0/169 | 0.363 | 0.097 |
| rec_20250821_151429 | development | baseline | rec_20250821_151429:expected:13 | no_alert_coverage | 0/170 | 0.317 | 0.105 |
| rec_20250821_151429 | development | baseline | rec_20250821_151429:expected:14 | no_alert_coverage | 0/163 | 0.386 | 0.083 |
| rec_20250821_151429 | development | baseline | rec_20250821_151429:expected:15 | no_alert_coverage | 0/166 | 0.348 | 0.096 |
| rec_20250821_151429 | development | selected | rec_20250821_151429:expected:3 | no_alert_coverage | 0/39 | 0.285 | 0.074 |
| rec_20250821_151429 | development | selected | rec_20250821_151429:expected:4 | no_alert_coverage | 0/143 | 0.281 | 0.091 |
| rec_20250821_151429 | development | selected | rec_20250821_151429:expected:6 | no_alert_coverage | 0/145 | 0.211 | 0.095 |
| rec_20250821_151429 | development | selected | rec_20250821_151429:expected:13 | no_alert_coverage | 0/170 | 0.317 | 0.105 |
| rec_20250821_151429 | development | selected | rec_20250821_151429:expected:15 | no_alert_coverage | 0/166 | 0.348 | 0.096 |
| rec_20250821_141846 | development | baseline | rec_20250821_141846:expected:1 | no_alert_coverage | 0/7 | 0.223 | 0.096 |
| rec_20250821_141846 | development | baseline | rec_20250821_141846:expected:3 | no_alert_coverage | 0/109 | 0.281 | 0.101 |
| rec_20250821_141846 | development | baseline | rec_20250821_141846:expected:5 | no_alert_coverage | 0/256 | 0.375 | 0.129 |
| rec_20250821_141846 | development | baseline | rec_20250821_141846:expected:8 | no_alert_coverage | 0/148 | 0.307 | 0.078 |
| rec_20250821_141846 | development | baseline | rec_20250821_141846:expected:9 | no_alert_coverage | 0/1 | 0.294 | 0.000 |
| rec_20250821_141846 | development | baseline | rec_20250821_141846:expected:10 | no_alert_coverage | 0/143 | 0.366 | 0.119 |
| rec_20250821_141846 | development | baseline | rec_20250821_141846:expected:11 | no_alert_coverage | 0/12 | 0.386 | 0.089 |
| rec_20250821_141846 | development | baseline | rec_20250821_141846:expected:12 | no_alert_coverage | 0/112 | 0.270 | 0.088 |
| rec_20250821_141846 | development | selected | rec_20250821_141846:expected:1 | no_alert_coverage | 0/7 | 0.223 | 0.096 |
| rec_20250821_141846 | development | selected | rec_20250821_141846:expected:3 | no_alert_coverage | 0/109 | 0.281 | 0.101 |
| rec_20250821_141846 | development | selected | rec_20250821_141846:expected:8 | no_alert_coverage | 0/148 | 0.307 | 0.078 |
| rec_20250821_141846 | development | selected | rec_20250821_141846:expected:9 | no_alert_coverage | 0/1 | 0.294 | 0.000 |
| rec_20250821_141846 | development | selected | rec_20250821_141846:expected:12 | no_alert_coverage | 0/112 | 0.270 | 0.088 |
| rec_20250821_132354 | development | baseline | rec_20250821_132354:expected:3 | no_alert_coverage | 0/29 | 0.234 | 0.100 |
| rec_20250821_132354 | development | baseline | rec_20250821_132354:expected:4 | no_alert_coverage | 0/20 | 0.346 | 0.150 |
| rec_20250821_132354 | development | baseline | rec_20250821_132354:expected:5 | no_alert_coverage | 0/1 | 0.186 | 0.000 |
| rec_20250821_132354 | development | baseline | rec_20250821_132354:expected:7 | no_alert_coverage | 0/1 | 0.297 | 0.113 |
| rec_20250821_132354 | development | baseline | rec_20250821_132354:expected:8 | no_alert_coverage | 0/54 | 0.364 | 0.131 |
| rec_20250821_132354 | development | baseline | rec_20250821_132354:expected:10 | no_alert_coverage | 0/193 | 0.255 | 0.091 |
| rec_20250821_132354 | development | baseline | rec_20250821_132354:expected:12 | no_alert_coverage | 0/427 | 0.398 | 0.086 |
| rec_20250821_132354 | development | baseline | rec_20250821_132354:expected:14 | no_alert_coverage | 0/154 | 0.299 | 0.129 |
| rec_20250821_132354 | development | baseline | rec_20250821_132354:expected:16 | no_alert_coverage | 0/154 | 0.232 | 0.090 |
| rec_20250821_132354 | development | baseline | rec_20250821_132354:expected:18 | no_alert_coverage | 0/269 | 0.382 | 0.087 |
| rec_20250821_132354 | development | selected | rec_20250821_132354:expected:3 | no_alert_coverage | 0/29 | 0.234 | 0.100 |
| rec_20250821_132354 | development | selected | rec_20250821_132354:expected:4 | no_alert_coverage | 0/20 | 0.346 | 0.150 |
| rec_20250821_132354 | development | selected | rec_20250821_132354:expected:5 | no_alert_coverage | 0/1 | 0.186 | 0.000 |
| rec_20250821_132354 | development | selected | rec_20250821_132354:expected:7 | no_alert_coverage | 0/1 | 0.297 | 0.113 |
| rec_20250821_132354 | development | selected | rec_20250821_132354:expected:8 | unmatched_with_alert_coverage | 8/54 | 0.364 | 0.131 |
| rec_20250821_132354 | development | selected | rec_20250821_132354:expected:10 | no_alert_coverage | 0/193 | 0.255 | 0.091 |
| rec_20250821_132354 | development | selected | rec_20250821_132354:expected:14 | no_alert_coverage | 0/154 | 0.299 | 0.129 |
| rec_20250821_132354 | development | selected | rec_20250821_132354:expected:16 | no_alert_coverage | 0/154 | 0.232 | 0.090 |
| rec_20250822_132819 | development | baseline | rec_20250822_132819:expected:2 | unmatched_with_alert_coverage | 70/70 | 0.892 | 0.103 |
| rec_20250822_132819 | development | baseline | rec_20250822_132819:expected:9 | unmatched_with_alert_coverage | 144/144 | 2.066 | 0.150 |
| rec_20250822_132819 | development | baseline | rec_20250822_132819:expected:12 | unmatched_with_alert_coverage | 4/4 | 0.470 | 0.134 |
| rec_20250822_132819 | development | baseline | rec_20250822_132819:expected:15 | no_alert_coverage | 0/34 | 0.341 | 0.054 |
| rec_20250822_132819 | development | baseline | rec_20250822_132819:expected:17 | unmatched_with_alert_coverage | 8/8 | 0.532 | 0.068 |
| rec_20250822_132819 | development | baseline | rec_20250822_132819:expected:18 | unmatched_with_alert_coverage | 210/210 | 2.170 | 1.753 |
| rec_20250822_132819 | development | baseline | rec_20250822_132819:expected:21 | no_alert_coverage | 0/44 | 0.339 | 0.054 |
| rec_20250822_132819 | development | baseline | rec_20250822_132819:expected:22 | no_alert_coverage | 0/1 | 0.343 | 0.000 |
| rec_20250822_132819 | development | baseline | rec_20250822_132819:expected:28 | unmatched_with_alert_coverage | 12/12 | 0.536 | 0.116 |
| rec_20250822_132819 | development | selected | rec_20250822_132819:expected:2 | unmatched_with_alert_coverage | 70/70 | 0.892 | 0.103 |
| rec_20250822_132819 | development | selected | rec_20250822_132819:expected:9 | unmatched_with_alert_coverage | 144/144 | 2.066 | 0.150 |
| rec_20250822_132819 | development | selected | rec_20250822_132819:expected:12 | unmatched_with_alert_coverage | 4/4 | 0.470 | 0.134 |
| rec_20250822_132819 | development | selected | rec_20250822_132819:expected:13 | unmatched_with_alert_coverage | 202/202 | 4.540 | 3.366 |
| rec_20250822_132819 | development | selected | rec_20250822_132819:expected:15 | no_alert_coverage | 0/34 | 0.341 | 0.054 |
| rec_20250822_132819 | development | selected | rec_20250822_132819:expected:17 | unmatched_with_alert_coverage | 8/8 | 0.532 | 0.068 |
| rec_20250822_132819 | development | selected | rec_20250822_132819:expected:18 | unmatched_with_alert_coverage | 210/210 | 2.170 | 1.753 |
| rec_20250822_132819 | development | selected | rec_20250822_132819:expected:21 | no_alert_coverage | 0/44 | 0.339 | 0.054 |
| rec_20250822_132819 | development | selected | rec_20250822_132819:expected:22 | no_alert_coverage | 0/1 | 0.343 | 0.000 |
| rec_20250822_132819 | development | selected | rec_20250822_132819:expected:28 | unmatched_with_alert_coverage | 12/12 | 0.536 | 0.116 |
| rec_20250822_135308 | development | baseline | rec_20250822_135308:expected:11 | no_alert_coverage | 0/8 | 0.331 | 0.029 |
| rec_20250822_135308 | development | baseline | rec_20250822_135308:expected:15 | no_alert_coverage | 0/87 | 0.390 | 0.147 |
| rec_20250822_135308 | development | baseline | rec_20250822_135308:expected:32 | no_alert_coverage | 0/83 | 0.386 | 0.068 |
| rec_20250822_135308 | development | baseline | rec_20250822_135308:expected:33 | no_alert_coverage | 0/379 | 0.344 | 0.085 |
| rec_20250822_135308 | development | selected | rec_20250822_135308:expected:11 | no_alert_coverage | 0/8 | 0.331 | 0.029 |
| rec_20250822_135308 | development | selected | rec_20250822_135308:expected:33 | no_alert_coverage | 0/379 | 0.344 | 0.085 |
| rec_20250822_123916 | development | baseline | rec_20250822_123916:expected:2 | no_alert_coverage | 0/1 | 0.307 | 0.063 |
| rec_20250822_123916 | development | baseline | rec_20250822_123916:expected:3 | no_alert_coverage | 0/59 | 0.314 | 0.119 |
| rec_20250822_123916 | development | baseline | rec_20250822_123916:expected:5 | no_alert_coverage | 0/133 | 0.230 | 0.102 |
| rec_20250822_123916 | development | baseline | rec_20250822_123916:expected:7 | no_alert_coverage | 0/95 | 0.304 | 0.108 |
| rec_20250822_123916 | development | baseline | rec_20250822_123916:expected:10 | no_alert_coverage | 0/124 | 0.302 | 0.085 |
| rec_20250822_123916 | development | baseline | rec_20250822_123916:expected:11 | no_alert_coverage | 0/63 | 0.340 | 0.135 |
| rec_20250822_123916 | development | baseline | rec_20250822_123916:expected:12 | no_alert_coverage | 0/184 | 0.272 | 0.092 |
| rec_20250822_123916 | development | selected | rec_20250822_123916:expected:2 | no_alert_coverage | 0/1 | 0.307 | 0.063 |
| rec_20250822_123916 | development | selected | rec_20250822_123916:expected:3 | no_alert_coverage | 0/59 | 0.314 | 0.119 |
| rec_20250822_123916 | development | selected | rec_20250822_123916:expected:5 | no_alert_coverage | 0/133 | 0.230 | 0.102 |
| rec_20250822_123916 | development | selected | rec_20250822_123916:expected:7 | no_alert_coverage | 0/95 | 0.304 | 0.108 |
| rec_20250822_123916 | development | selected | rec_20250822_123916:expected:10 | no_alert_coverage | 0/124 | 0.302 | 0.085 |
| rec_20250822_123916 | development | selected | rec_20250822_123916:expected:11 | no_alert_coverage | 0/63 | 0.340 | 0.135 |
| rec_20250822_123916 | development | selected | rec_20250822_123916:expected:12 | no_alert_coverage | 0/184 | 0.272 | 0.092 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:2 | no_alert_coverage | 0/163 | 0.260 | 0.092 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:4 | no_alert_coverage | 0/190 | 0.324 | 0.099 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:6 | no_alert_coverage | 0/18 | 0.212 | 0.000 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:7 | no_alert_coverage | 0/112 | 0.234 | 0.063 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:8 | no_alert_coverage | 0/150 | 0.332 | 0.079 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:9 | no_alert_coverage | 0/416 | 0.386 | 0.099 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:11 | no_alert_coverage | 0/31 | 0.266 | 0.075 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:12 | no_alert_coverage | 0/100 | 0.307 | 0.105 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:14 | no_alert_coverage | 0/106 | 0.273 | 0.103 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:16 | no_alert_coverage | 0/200 | 0.364 | 0.118 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:17 | no_alert_coverage | 0/354 | 0.393 | 0.095 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:19 | no_alert_coverage | 0/164 | 0.229 | 0.108 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:21 | no_alert_coverage | 0/122 | 0.338 | 0.099 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:23 | no_alert_coverage | 0/169 | 0.379 | 0.128 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:24 | no_alert_coverage | 0/4 | 0.292 | 0.000 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:25 | no_alert_coverage | 0/87 | 0.301 | 0.105 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:27 | no_alert_coverage | 0/104 | 0.239 | 0.094 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:29 | no_alert_coverage | 0/72 | 0.331 | 0.106 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:32 | no_alert_coverage | 0/120 | 0.216 | 0.087 |
| rec_20250828_105714 | evaluation | baseline | rec_20250828_105714:expected:34 | no_alert_coverage | 0/1 | 0.237 | 0.000 |
| rec_20250828_105714 | evaluation | selected | rec_20250828_105714:expected:2 | no_alert_coverage | 0/163 | 0.260 | 0.092 |
| rec_20250828_105714 | evaluation | selected | rec_20250828_105714:expected:4 | no_alert_coverage | 0/190 | 0.324 | 0.099 |
| rec_20250828_105714 | evaluation | selected | rec_20250828_105714:expected:6 | no_alert_coverage | 0/18 | 0.212 | 0.000 |
| rec_20250828_105714 | evaluation | selected | rec_20250828_105714:expected:7 | no_alert_coverage | 0/112 | 0.234 | 0.063 |
| rec_20250828_105714 | evaluation | selected | rec_20250828_105714:expected:8 | no_alert_coverage | 0/150 | 0.332 | 0.079 |
| rec_20250828_105714 | evaluation | selected | rec_20250828_105714:expected:11 | no_alert_coverage | 0/31 | 0.266 | 0.075 |
| rec_20250828_105714 | evaluation | selected | rec_20250828_105714:expected:12 | no_alert_coverage | 0/100 | 0.307 | 0.105 |
| rec_20250828_105714 | evaluation | selected | rec_20250828_105714:expected:14 | no_alert_coverage | 0/106 | 0.273 | 0.103 |
| rec_20250828_105714 | evaluation | selected | rec_20250828_105714:expected:19 | no_alert_coverage | 0/164 | 0.229 | 0.108 |
| rec_20250828_105714 | evaluation | selected | rec_20250828_105714:expected:21 | no_alert_coverage | 0/122 | 0.338 | 0.099 |
| rec_20250828_105714 | evaluation | selected | rec_20250828_105714:expected:24 | no_alert_coverage | 0/4 | 0.292 | 0.000 |
| rec_20250828_105714 | evaluation | selected | rec_20250828_105714:expected:25 | no_alert_coverage | 0/87 | 0.301 | 0.105 |
| rec_20250828_105714 | evaluation | selected | rec_20250828_105714:expected:27 | no_alert_coverage | 0/104 | 0.239 | 0.094 |
| rec_20250828_105714 | evaluation | selected | rec_20250828_105714:expected:29 | no_alert_coverage | 0/72 | 0.331 | 0.106 |
| rec_20250828_105714 | evaluation | selected | rec_20250828_105714:expected:32 | no_alert_coverage | 0/120 | 0.216 | 0.087 |
| rec_20250828_105714 | evaluation | selected | rec_20250828_105714:expected:34 | no_alert_coverage | 0/1 | 0.237 | 0.000 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:4 | no_alert_coverage | 0/125 | 0.215 | 0.089 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:6 | no_alert_coverage | 0/313 | 0.334 | 0.083 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:7 | no_alert_coverage | 0/105 | 0.318 | 0.086 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:9 | no_alert_coverage | 0/87 | 0.269 | 0.107 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:11 | no_alert_coverage | 0/192 | 0.399 | 0.117 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:13 | no_alert_coverage | 0/97 | 0.212 | 0.100 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:15 | no_alert_coverage | 0/29 | 0.205 | 0.026 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:16 | no_alert_coverage | 0/637 | 0.383 | 0.107 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:17 | no_alert_coverage | 0/20 | 0.324 | 0.095 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:20 | no_alert_coverage | 0/61 | 0.270 | 0.060 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:21 | no_alert_coverage | 0/4 | 0.256 | 0.000 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:23 | no_alert_coverage | 0/419 | 0.398 | 0.126 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:24 | no_alert_coverage | 0/250 | 0.227 | 0.087 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:26 | no_alert_coverage | 0/182 | 0.328 | 0.110 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:29 | no_alert_coverage | 0/237 | 0.389 | 0.111 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:30 | no_alert_coverage | 0/106 | 0.339 | 0.098 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:34 | no_alert_coverage | 0/97 | 0.307 | 0.099 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:36 | no_alert_coverage | 0/89 | 0.248 | 0.096 |
| rec_20250828_161448 | evaluation | baseline | rec_20250828_161448:expected:38 | no_alert_coverage | 0/193 | 0.310 | 0.119 |
| rec_20250828_161448 | evaluation | selected | rec_20250828_161448:expected:4 | no_alert_coverage | 0/125 | 0.215 | 0.089 |
| rec_20250828_161448 | evaluation | selected | rec_20250828_161448:expected:6 | no_alert_coverage | 0/313 | 0.334 | 0.083 |
| rec_20250828_161448 | evaluation | selected | rec_20250828_161448:expected:7 | no_alert_coverage | 0/105 | 0.318 | 0.086 |
| rec_20250828_161448 | evaluation | selected | rec_20250828_161448:expected:9 | no_alert_coverage | 0/87 | 0.269 | 0.107 |
| rec_20250828_161448 | evaluation | selected | rec_20250828_161448:expected:11 | unmatched_with_alert_coverage | 55/192 | 0.399 | 0.117 |
| rec_20250828_161448 | evaluation | selected | rec_20250828_161448:expected:13 | no_alert_coverage | 0/97 | 0.212 | 0.100 |
| rec_20250828_161448 | evaluation | selected | rec_20250828_161448:expected:15 | no_alert_coverage | 0/29 | 0.205 | 0.026 |
| rec_20250828_161448 | evaluation | selected | rec_20250828_161448:expected:17 | no_alert_coverage | 0/20 | 0.324 | 0.095 |
| rec_20250828_161448 | evaluation | selected | rec_20250828_161448:expected:20 | no_alert_coverage | 0/61 | 0.270 | 0.060 |
| rec_20250828_161448 | evaluation | selected | rec_20250828_161448:expected:21 | no_alert_coverage | 0/4 | 0.256 | 0.000 |
| rec_20250828_161448 | evaluation | selected | rec_20250828_161448:expected:24 | no_alert_coverage | 0/250 | 0.227 | 0.087 |
| rec_20250828_161448 | evaluation | selected | rec_20250828_161448:expected:26 | no_alert_coverage | 0/182 | 0.328 | 0.110 |
| rec_20250828_161448 | evaluation | selected | rec_20250828_161448:expected:30 | no_alert_coverage | 0/106 | 0.339 | 0.098 |
| rec_20250828_161448 | evaluation | selected | rec_20250828_161448:expected:34 | no_alert_coverage | 0/97 | 0.307 | 0.099 |
| rec_20250828_161448 | evaluation | selected | rec_20250828_161448:expected:36 | no_alert_coverage | 0/89 | 0.248 | 0.096 |
| rec_20250828_161448 | evaluation | selected | rec_20250828_161448:expected:38 | no_alert_coverage | 0/193 | 0.310 | 0.119 |
| rec_20250825_100748 | evaluation | baseline | rec_20250825_100748:expected:2 | no_alert_coverage | 0/328 | 0.386 | 0.129 |
| rec_20250825_100748 | evaluation | baseline | rec_20250825_100748:expected:3 | no_alert_coverage | 0/128 | 0.313 | 0.089 |
| rec_20250825_100748 | evaluation | baseline | rec_20250825_100748:expected:6 | no_alert_coverage | 0/228 | 0.249 | 0.126 |
| rec_20250825_100748 | evaluation | baseline | rec_20250825_100748:expected:10 | no_alert_coverage | 0/152 | 0.212 | 0.073 |
| rec_20250825_100748 | evaluation | baseline | rec_20250825_100748:expected:12 | no_alert_coverage | 0/100 | 0.205 | 0.096 |
| rec_20250825_100748 | evaluation | baseline | rec_20250825_100748:expected:14 | no_alert_coverage | 0/50 | 0.290 | 0.052 |
| rec_20250825_100748 | evaluation | baseline | rec_20250825_100748:expected:15 | no_alert_coverage | 0/100 | 0.284 | 0.105 |
| rec_20250825_100748 | evaluation | baseline | rec_20250825_100748:expected:17 | no_alert_coverage | 0/112 | 0.267 | 0.088 |
| rec_20250825_100748 | evaluation | baseline | rec_20250825_100748:expected:19 | no_alert_coverage | 0/101 | 0.282 | 0.100 |
| rec_20250825_100748 | evaluation | baseline | rec_20250825_100748:expected:21 | no_alert_coverage | 0/101 | 0.268 | 0.142 |
| rec_20250825_100748 | evaluation | selected | rec_20250825_100748:expected:3 | no_alert_coverage | 0/128 | 0.313 | 0.089 |
| rec_20250825_100748 | evaluation | selected | rec_20250825_100748:expected:6 | no_alert_coverage | 0/228 | 0.249 | 0.126 |
| rec_20250825_100748 | evaluation | selected | rec_20250825_100748:expected:10 | no_alert_coverage | 0/152 | 0.212 | 0.073 |
| rec_20250825_100748 | evaluation | selected | rec_20250825_100748:expected:12 | no_alert_coverage | 0/100 | 0.205 | 0.096 |
| rec_20250825_100748 | evaluation | selected | rec_20250825_100748:expected:14 | no_alert_coverage | 0/50 | 0.290 | 0.052 |
| rec_20250825_100748 | evaluation | selected | rec_20250825_100748:expected:15 | no_alert_coverage | 0/100 | 0.284 | 0.105 |
| rec_20250825_100748 | evaluation | selected | rec_20250825_100748:expected:17 | no_alert_coverage | 0/112 | 0.267 | 0.088 |
| rec_20250825_100748 | evaluation | selected | rec_20250825_100748:expected:19 | no_alert_coverage | 0/101 | 0.282 | 0.100 |
| rec_20250825_100748 | evaluation | selected | rec_20250825_100748:expected:21 | no_alert_coverage | 0/101 | 0.268 | 0.142 |
| rec_20250825_133605 | development | baseline | rec_20250825_133605:expected:3 | unmatched_with_alert_coverage | 16/16 | 0.596 | 0.074 |
| rec_20250825_133605 | development | baseline | rec_20250825_133605:expected:4 | unmatched_with_alert_coverage | 428/428 | 0.932 | 0.144 |
| rec_20250825_133605 | development | baseline | rec_20250825_133605:expected:5 | unmatched_with_alert_coverage | 150/150 | 2.745 | 3.498 |
| rec_20250825_133605 | development | baseline | rec_20250825_133605:expected:12 | unmatched_with_alert_coverage | 32/32 | 0.776 | 0.095 |
| rec_20250825_133605 | development | baseline | rec_20250825_133605:expected:13 | unmatched_with_alert_coverage | 189/189 | 1.017 | 0.252 |
| rec_20250825_133605 | development | baseline | rec_20250825_133605:expected:18 | unmatched_with_alert_coverage | 4/4 | 0.410 | 0.118 |
| rec_20250825_133605 | development | baseline | rec_20250825_133605:expected:21 | unmatched_with_alert_coverage | 22/22 | 0.500 | 0.047 |
| rec_20250825_133605 | development | baseline | rec_20250825_133605:expected:22 | unmatched_with_alert_coverage | 204/204 | 0.767 | 0.084 |
| rec_20250825_133605 | development | baseline | rec_20250825_133605:expected:23 | unmatched_with_alert_coverage | 325/325 | 0.835 | 0.116 |
| rec_20250825_133605 | development | baseline | rec_20250825_133605:expected:24 | unmatched_with_alert_coverage | 183/183 | 2.637 | 3.726 |
| rec_20250825_133605 | development | selected | rec_20250825_133605:expected:3 | unmatched_with_alert_coverage | 16/16 | 0.596 | 0.074 |
| rec_20250825_133605 | development | selected | rec_20250825_133605:expected:4 | unmatched_with_alert_coverage | 428/428 | 0.932 | 0.144 |
| rec_20250825_133605 | development | selected | rec_20250825_133605:expected:5 | unmatched_with_alert_coverage | 150/150 | 2.745 | 3.498 |
| rec_20250825_133605 | development | selected | rec_20250825_133605:expected:12 | unmatched_with_alert_coverage | 32/32 | 0.776 | 0.095 |
| rec_20250825_133605 | development | selected | rec_20250825_133605:expected:13 | unmatched_with_alert_coverage | 189/189 | 1.017 | 0.252 |
| rec_20250825_133605 | development | selected | rec_20250825_133605:expected:18 | unmatched_with_alert_coverage | 4/4 | 0.410 | 0.118 |
| rec_20250825_133605 | development | selected | rec_20250825_133605:expected:19 | unmatched_with_alert_coverage | 362/362 | 1.653 | 1.842 |
| rec_20250825_133605 | development | selected | rec_20250825_133605:expected:21 | unmatched_with_alert_coverage | 22/22 | 0.500 | 0.047 |
| rec_20250825_133605 | development | selected | rec_20250825_133605:expected:22 | unmatched_with_alert_coverage | 204/204 | 0.767 | 0.084 |
| rec_20250825_133605 | development | selected | rec_20250825_133605:expected:23 | unmatched_with_alert_coverage | 325/325 | 0.835 | 0.116 |
| rec_20250825_133605 | development | selected | rec_20250825_133605:expected:24 | unmatched_with_alert_coverage | 183/183 | 2.637 | 3.726 |
| rec_20250825_133605 | development | selected | rec_20250825_133605:expected:27 | unmatched_with_alert_coverage | 123/123 | 2.426 | 3.128 |
| rec_20250825_135829 | development | baseline | rec_20250825_135829:expected:6 | unmatched_with_alert_coverage | 297/297 | 2.098 | 1.338 |
| rec_20250825_135829 | development | baseline | rec_20250825_135829:expected:10 | no_alert_coverage | 0/4 | 0.325 | 0.092 |
| rec_20250825_135829 | development | baseline | rec_20250825_135829:expected:12 | unmatched_with_alert_coverage | 106/106 | 0.462 | 0.160 |
| rec_20250825_135829 | development | baseline | rec_20250825_135829:expected:18 | no_alert_coverage | 0/4 | 0.309 | 0.099 |
| rec_20250825_135829 | development | baseline | rec_20250825_135829:expected:21 | unmatched_with_alert_coverage | 86/86 | 0.805 | 0.217 |
| rec_20250825_135829 | development | baseline | rec_20250825_135829:expected:24 | unmatched_with_alert_coverage | 3/3 | 0.867 | 0.055 |
| rec_20250825_135829 | development | baseline | rec_20250825_135829:expected:26 | unmatched_with_alert_coverage | 141/141 | 2.816 | 3.782 |
| rec_20250825_135829 | development | baseline | rec_20250825_135829:expected:29 | unmatched_with_alert_coverage | 43/43 | 0.655 | 0.000 |
| rec_20250825_135829 | development | selected | rec_20250825_135829:expected:6 | unmatched_with_alert_coverage | 297/297 | 2.098 | 1.338 |
| rec_20250825_135829 | development | selected | rec_20250825_135829:expected:10 | no_alert_coverage | 0/4 | 0.325 | 0.092 |
| rec_20250825_135829 | development | selected | rec_20250825_135829:expected:12 | unmatched_with_alert_coverage | 106/106 | 0.462 | 0.160 |
| rec_20250825_135829 | development | selected | rec_20250825_135829:expected:18 | no_alert_coverage | 0/4 | 0.309 | 0.099 |
| rec_20250825_135829 | development | selected | rec_20250825_135829:expected:21 | unmatched_with_alert_coverage | 86/86 | 0.805 | 0.217 |
| rec_20250825_135829 | development | selected | rec_20250825_135829:expected:24 | unmatched_with_alert_coverage | 3/3 | 0.867 | 0.055 |
| rec_20250825_135829 | development | selected | rec_20250825_135829:expected:26 | unmatched_with_alert_coverage | 141/141 | 2.816 | 3.782 |
| rec_20250825_135829 | development | selected | rec_20250825_135829:expected:29 | unmatched_with_alert_coverage | 43/43 | 0.655 | 0.000 |
| rec_20250829_104641 | development | baseline | rec_20250829_104641:expected:1 | no_alert_coverage | 0/51 | 0.361 | 0.132 |
| rec_20250829_104641 | development | baseline | rec_20250829_104641:expected:3 | no_alert_coverage | 0/195 | 0.282 | 0.079 |
| rec_20250829_104641 | development | baseline | rec_20250829_104641:expected:5 | no_alert_coverage | 0/74 | 0.362 | 0.111 |
| rec_20250829_104641 | development | baseline | rec_20250829_104641:expected:11 | no_alert_coverage | 0/52 | 0.242 | 0.124 |
| rec_20250829_104641 | development | baseline | rec_20250829_104641:expected:13 | no_alert_coverage | 0/91 | 0.237 | 0.095 |
| rec_20250829_104641 | development | baseline | rec_20250829_104641:expected:21 | no_alert_coverage | 0/3 | 0.212 | 0.000 |
| rec_20250829_104641 | development | baseline | rec_20250829_104641:expected:22 | no_alert_coverage | 0/281 | 0.355 | 0.090 |
| rec_20250829_104641 | development | baseline | rec_20250829_104641:expected:24 | no_alert_coverage | 0/133 | 0.391 | 0.133 |
| rec_20250829_104641 | development | baseline | rec_20250829_104641:expected:25 | no_alert_coverage | 0/142 | 0.264 | 0.080 |
| rec_20250829_104641 | development | selected | rec_20250829_104641:expected:3 | no_alert_coverage | 0/195 | 0.282 | 0.079 |
| rec_20250829_104641 | development | selected | rec_20250829_104641:expected:11 | no_alert_coverage | 0/52 | 0.242 | 0.124 |
| rec_20250829_104641 | development | selected | rec_20250829_104641:expected:13 | no_alert_coverage | 0/91 | 0.237 | 0.095 |
| rec_20250829_104641 | development | selected | rec_20250829_104641:expected:21 | no_alert_coverage | 0/3 | 0.212 | 0.000 |
| rec_20250829_104641 | development | selected | rec_20250829_104641:expected:22 | no_alert_coverage | 0/281 | 0.355 | 0.090 |
| rec_20250829_104641 | development | selected | rec_20250829_104641:expected:25 | no_alert_coverage | 0/142 | 0.264 | 0.080 |
| rec_20250825_161940 | development | baseline | rec_20250825_161940:expected:2 | unmatched_with_alert_coverage | 15/15 | 0.609 | 0.085 |
| rec_20250825_161940 | development | baseline | rec_20250825_161940:expected:14 | no_alert_coverage | 0/50 | 0.377 | 0.142 |
| rec_20250825_161940 | development | baseline | rec_20250825_161940:expected:21 | no_alert_coverage | 0/3 | 0.332 | 0.046 |
| rec_20250825_161940 | development | baseline | rec_20250825_161940:expected:24 | unmatched_with_alert_coverage | 5/5 | 0.742 | 0.114 |
| rec_20250825_161940 | development | baseline | rec_20250825_161940:expected:25 | unmatched_with_alert_coverage | 256/256 | 3.713 | 5.168 |
| rec_20250825_161940 | development | baseline | rec_20250825_161940:expected:28 | unmatched_with_alert_coverage | 15/15 | 0.606 | 0.097 |
| rec_20250825_161940 | development | baseline | rec_20250825_161940:expected:29 | unmatched_with_alert_coverage | 278/278 | 3.775 | 6.656 |
| rec_20250825_161940 | development | selected | rec_20250825_161940:expected:2 | unmatched_with_alert_coverage | 15/15 | 0.609 | 0.085 |
| rec_20250825_161940 | development | selected | rec_20250825_161940:expected:9 | unmatched_with_alert_coverage | 129/129 | 1.964 | 2.585 |
| rec_20250825_161940 | development | selected | rec_20250825_161940:expected:16 | unmatched_with_alert_coverage | 347/372 | 11.696 | 6.609 |
| rec_20250825_161940 | development | selected | rec_20250825_161940:expected:21 | no_alert_coverage | 0/3 | 0.332 | 0.046 |
| rec_20250825_161940 | development | selected | rec_20250825_161940:expected:24 | unmatched_with_alert_coverage | 5/5 | 0.742 | 0.114 |
| rec_20250825_161940 | development | selected | rec_20250825_161940:expected:25 | unmatched_with_alert_coverage | 256/256 | 3.713 | 5.168 |
| rec_20250825_161940 | development | selected | rec_20250825_161940:expected:28 | unmatched_with_alert_coverage | 15/15 | 0.606 | 0.097 |
| rec_20250825_161940 | development | selected | rec_20250825_161940:expected:29 | unmatched_with_alert_coverage | 278/278 | 3.775 | 6.656 |
| rec_20250825_145941 | development | baseline | rec_20250825_145941:expected:1 | no_alert_coverage | 0/61 | 0.362 | 0.029 |
| rec_20250825_145941 | development | baseline | rec_20250825_145941:expected:2 | no_alert_coverage | 0/23 | 0.355 | 0.000 |
| rec_20250825_145941 | development | baseline | rec_20250825_145941:expected:4 | no_alert_coverage | 0/122 | 0.192 | 0.091 |
| rec_20250825_145941 | development | baseline | rec_20250825_145941:expected:6 | no_alert_coverage | 0/117 | 0.318 | 0.079 |
| rec_20250825_145941 | development | baseline | rec_20250825_145941:expected:8 | no_alert_coverage | 0/26 | 0.338 | 0.078 |
| rec_20250825_145941 | development | baseline | rec_20250825_145941:expected:9 | no_alert_coverage | 0/87 | 0.304 | 0.098 |
| rec_20250825_145941 | development | baseline | rec_20250825_145941:expected:11 | no_alert_coverage | 0/243 | 0.341 | 0.106 |
| rec_20250825_145941 | development | selected | rec_20250825_145941:expected:2 | no_alert_coverage | 0/23 | 0.355 | 0.000 |
| rec_20250825_145941 | development | selected | rec_20250825_145941:expected:4 | no_alert_coverage | 0/122 | 0.192 | 0.091 |
| rec_20250825_145941 | development | selected | rec_20250825_145941:expected:6 | no_alert_coverage | 0/117 | 0.318 | 0.079 |
| rec_20250825_145941 | development | selected | rec_20250825_145941:expected:8 | no_alert_coverage | 0/26 | 0.338 | 0.078 |
| rec_20250825_145941 | development | selected | rec_20250825_145941:expected:9 | no_alert_coverage | 0/87 | 0.304 | 0.098 |
| rec_20250825_145941 | development | selected | rec_20250825_145941:expected:11 | no_alert_coverage | 0/243 | 0.341 | 0.106 |
| rec_20250825_153216 | development | baseline | rec_20250825_153216:expected:17 | no_alert_coverage | 0/132 | 0.368 | 0.123 |
| rec_20250825_153216 | development | baseline | rec_20250825_153216:expected:25 | no_alert_coverage | 0/20 | 0.368 | 0.124 |
| rec_20250825_153216 | development | baseline | rec_20250825_153216:expected:26 | no_alert_coverage | 0/4 | 0.363 | 0.100 |
| rec_20250825_153216 | development | baseline | rec_20250825_153216:expected:34 | unmatched_with_alert_coverage | 208/208 | 0.503 | 0.085 |
| rec_20250825_153216 | development | selected | rec_20250825_153216:expected:25 | unmatched_with_alert_coverage | 4/20 | 0.368 | 0.124 |
| rec_20250825_153216 | development | selected | rec_20250825_153216:expected:28 | unmatched_with_alert_coverage | 274/274 | 0.732 | 0.088 |
| rec_20250825_153216 | development | selected | rec_20250825_153216:expected:29 | unmatched_with_alert_coverage | 336/336 | 3.060 | 3.063 |
| rec_20250825_153216 | development | selected | rec_20250825_153216:expected:34 | unmatched_with_alert_coverage | 208/208 | 0.503 | 0.085 |
| rec_20250826_104543 | evaluation | baseline | rec_20250826_104543:expected:6 | no_alert_coverage | 0/12 | 0.385 | 0.059 |
| rec_20250826_104543 | evaluation | baseline | rec_20250826_104543:expected:7 | no_alert_coverage | 0/107 | 0.355 | 0.104 |
| rec_20250826_104543 | evaluation | baseline | rec_20250826_104543:expected:9 | no_alert_coverage | 0/133 | 0.334 | 0.104 |
| rec_20250826_104543 | evaluation | baseline | rec_20250826_104543:expected:11 | no_alert_coverage | 0/61 | 0.290 | 0.091 |
| rec_20250826_104543 | evaluation | baseline | rec_20250826_104543:expected:12 | no_alert_coverage | 0/3 | 0.348 | 0.087 |
| rec_20250826_104543 | evaluation | baseline | rec_20250826_104543:expected:14 | no_alert_coverage | 0/193 | 0.269 | 0.141 |
| rec_20250826_104543 | evaluation | baseline | rec_20250826_104543:expected:16 | no_alert_coverage | 0/224 | 0.384 | 0.069 |
| rec_20250826_104543 | evaluation | baseline | rec_20250826_104543:expected:17 | no_alert_coverage | 0/816 | 0.396 | 0.122 |
| rec_20250826_104543 | evaluation | baseline | rec_20250826_104543:expected:19 | no_alert_coverage | 0/1 | 0.277 | 0.000 |
| rec_20250826_104543 | evaluation | baseline | rec_20250826_104543:expected:20 | no_alert_coverage | 0/16 | 0.318 | 0.095 |
| rec_20250826_104543 | evaluation | baseline | rec_20250826_104543:expected:22 | no_alert_coverage | 0/2 | 0.204 | 0.044 |
| rec_20250826_104543 | evaluation | baseline | rec_20250826_104543:expected:26 | no_alert_coverage | 0/16 | 0.341 | 0.143 |
| rec_20250826_104543 | evaluation | baseline | rec_20250826_104543:expected:27 | no_alert_coverage | 0/19 | 0.375 | 0.064 |
| rec_20250826_104543 | evaluation | selected | rec_20250826_104543:expected:7 | no_alert_coverage | 0/107 | 0.355 | 0.104 |
| rec_20250826_104543 | evaluation | selected | rec_20250826_104543:expected:9 | no_alert_coverage | 0/133 | 0.334 | 0.104 |
| rec_20250826_104543 | evaluation | selected | rec_20250826_104543:expected:11 | no_alert_coverage | 0/61 | 0.290 | 0.091 |
| rec_20250826_104543 | evaluation | selected | rec_20250826_104543:expected:12 | no_alert_coverage | 0/3 | 0.348 | 0.087 |
| rec_20250826_104543 | evaluation | selected | rec_20250826_104543:expected:14 | no_alert_coverage | 0/193 | 0.269 | 0.141 |
| rec_20250826_104543 | evaluation | selected | rec_20250826_104543:expected:19 | no_alert_coverage | 0/1 | 0.277 | 0.000 |
| rec_20250826_104543 | evaluation | selected | rec_20250826_104543:expected:20 | no_alert_coverage | 0/16 | 0.318 | 0.095 |
| rec_20250826_104543 | evaluation | selected | rec_20250826_104543:expected:22 | no_alert_coverage | 0/2 | 0.204 | 0.044 |
| rec_20250826_104543 | evaluation | selected | rec_20250826_104543:expected:26 | no_alert_coverage | 0/16 | 0.341 | 0.143 |
| rec_20250826_095810 | evaluation | baseline | rec_20250826_095810:expected:2 | no_alert_coverage | 0/119 | 0.252 | 0.083 |
| rec_20250826_095810 | evaluation | baseline | rec_20250826_095810:expected:5 | no_alert_coverage | 0/101 | 0.336 | 0.129 |
| rec_20250826_095810 | evaluation | baseline | rec_20250826_095810:expected:6 | no_alert_coverage | 0/71 | 0.267 | 0.098 |
| rec_20250826_095810 | evaluation | baseline | rec_20250826_095810:expected:9 | no_alert_coverage | 0/123 | 0.361 | 0.109 |
| rec_20250826_095810 | evaluation | baseline | rec_20250826_095810:expected:11 | no_alert_coverage | 0/181 | 0.385 | 0.096 |
| rec_20250826_095810 | evaluation | baseline | rec_20250826_095810:expected:13 | no_alert_coverage | 0/142 | 0.326 | 0.113 |
| rec_20250826_095810 | evaluation | baseline | rec_20250826_095810:expected:14 | no_alert_coverage | 0/73 | 0.266 | 0.083 |
| rec_20250826_095810 | evaluation | baseline | rec_20250826_095810:expected:15 | no_alert_coverage | 0/1 | 0.216 | 0.000 |
| rec_20250826_095810 | evaluation | baseline | rec_20250826_095810:expected:18 | no_alert_coverage | 0/116 | 0.243 | 0.078 |
| rec_20250826_095810 | evaluation | baseline | rec_20250826_095810:expected:20 | no_alert_coverage | 0/71 | 0.306 | 0.067 |
| rec_20250826_095810 | evaluation | baseline | rec_20250826_095810:expected:21 | no_alert_coverage | 0/24 | 0.249 | 0.057 |
| rec_20250826_095810 | evaluation | baseline | rec_20250826_095810:expected:22 | no_alert_coverage | 0/84 | 0.258 | 0.098 |
| rec_20250826_095810 | evaluation | baseline | rec_20250826_095810:expected:25 | no_alert_coverage | 0/31 | 0.298 | 0.113 |
| rec_20250826_095810 | evaluation | baseline | rec_20250826_095810:expected:26 | no_alert_coverage | 0/169 | 0.382 | 0.090 |
| rec_20250826_095810 | evaluation | baseline | rec_20250826_095810:expected:28 | no_alert_coverage | 0/114 | 0.379 | 0.105 |
| rec_20250826_095810 | evaluation | selected | rec_20250826_095810:expected:2 | no_alert_coverage | 0/119 | 0.252 | 0.083 |
| rec_20250826_095810 | evaluation | selected | rec_20250826_095810:expected:5 | no_alert_coverage | 0/101 | 0.336 | 0.129 |
| rec_20250826_095810 | evaluation | selected | rec_20250826_095810:expected:6 | no_alert_coverage | 0/71 | 0.267 | 0.098 |
| rec_20250826_095810 | evaluation | selected | rec_20250826_095810:expected:13 | no_alert_coverage | 0/142 | 0.326 | 0.113 |
| rec_20250826_095810 | evaluation | selected | rec_20250826_095810:expected:14 | no_alert_coverage | 0/73 | 0.266 | 0.083 |
| rec_20250826_095810 | evaluation | selected | rec_20250826_095810:expected:15 | no_alert_coverage | 0/1 | 0.216 | 0.000 |
| rec_20250826_095810 | evaluation | selected | rec_20250826_095810:expected:18 | no_alert_coverage | 0/116 | 0.243 | 0.078 |
| rec_20250826_095810 | evaluation | selected | rec_20250826_095810:expected:20 | no_alert_coverage | 0/71 | 0.306 | 0.067 |
| rec_20250826_095810 | evaluation | selected | rec_20250826_095810:expected:21 | no_alert_coverage | 0/24 | 0.249 | 0.057 |
| rec_20250826_095810 | evaluation | selected | rec_20250826_095810:expected:22 | no_alert_coverage | 0/84 | 0.258 | 0.098 |
| rec_20250826_095810 | evaluation | selected | rec_20250826_095810:expected:25 | no_alert_coverage | 0/31 | 0.298 | 0.113 |
| rec_20250826_102611 | evaluation | baseline | rec_20250826_102611:expected:3 | no_alert_coverage | 0/34 | 0.272 | 0.107 |
| rec_20250826_102611 | evaluation | baseline | rec_20250826_102611:expected:4 | no_alert_coverage | 0/1 | 0.287 | 0.000 |
| rec_20250826_102611 | evaluation | baseline | rec_20250826_102611:expected:5 | no_alert_coverage | 0/139 | 0.336 | 0.127 |
| rec_20250826_102611 | evaluation | baseline | rec_20250826_102611:expected:9 | no_alert_coverage | 0/87 | 0.334 | 0.107 |
| rec_20250826_102611 | evaluation | baseline | rec_20250826_102611:expected:11 | no_alert_coverage | 0/100 | 0.285 | 0.085 |
| rec_20250826_102611 | evaluation | baseline | rec_20250826_102611:expected:14 | no_alert_coverage | 0/127 | 0.212 | 0.077 |
| rec_20250826_102611 | evaluation | baseline | rec_20250826_102611:expected:16 | no_alert_coverage | 0/109 | 0.224 | 0.089 |
| rec_20250826_102611 | evaluation | baseline | rec_20250826_102611:expected:18 | no_alert_coverage | 0/96 | 0.267 | 0.102 |
| rec_20250826_102611 | evaluation | baseline | rec_20250826_102611:expected:20 | no_alert_coverage | 0/106 | 0.241 | 0.091 |
| rec_20250826_102611 | evaluation | selected | rec_20250826_102611:expected:3 | no_alert_coverage | 0/34 | 0.272 | 0.107 |
| rec_20250826_102611 | evaluation | selected | rec_20250826_102611:expected:4 | no_alert_coverage | 0/1 | 0.287 | 0.000 |
| rec_20250826_102611 | evaluation | selected | rec_20250826_102611:expected:5 | no_alert_coverage | 0/139 | 0.336 | 0.127 |
| rec_20250826_102611 | evaluation | selected | rec_20250826_102611:expected:9 | no_alert_coverage | 0/87 | 0.334 | 0.107 |
| rec_20250826_102611 | evaluation | selected | rec_20250826_102611:expected:11 | no_alert_coverage | 0/100 | 0.285 | 0.085 |
| rec_20250826_102611 | evaluation | selected | rec_20250826_102611:expected:14 | no_alert_coverage | 0/127 | 0.212 | 0.077 |
| rec_20250826_102611 | evaluation | selected | rec_20250826_102611:expected:16 | no_alert_coverage | 0/109 | 0.224 | 0.089 |
| rec_20250826_102611 | evaluation | selected | rec_20250826_102611:expected:18 | no_alert_coverage | 0/96 | 0.267 | 0.102 |
| rec_20250826_102611 | evaluation | selected | rec_20250826_102611:expected:20 | no_alert_coverage | 0/106 | 0.241 | 0.091 |

## Methodology and limits

- Selection maximizes development macro sample F1 with precision at least baseline minus 0.05 and event recall at least baseline. Only the baseline and selected configuration are evaluated on the held-out environments.
- F1 ties prefer a shorter recovery hold, then a higher spread threshold, then heading disabled; remaining ties keep manifest order. These simplicity preferences use development results only.
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
