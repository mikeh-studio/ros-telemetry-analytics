# Localization Integrity Evaluation

Dataset: TUHH Robot Localization Failure Prediction Dataset  
Run: `rec_20250821_104113` (warehouse, dynamic and static obstacles)  
Scope: both processed Parquet members, **15,708 samples**  
Labeled failures: **4,537** (0.289)

## Observable-only baseline

The detector uses particle-cloud position spread above 0.4 m or a consecutive
AMCL pose jump above 0.5 m. Ground-truth pose, position error, heading error,
and `is_delocalized` are used only for scoring.

| Level | Precision | Recall | F1 / false alarms |
| --- | ---: | ---: | ---: |
| Samples | 0.856 | 0.468 | 0.605 F1 |
| Events | 0.842 | 0.667 | 3 false-alarm events |

Events merge label or detector flicker separated by at most 500 ms and use a
100 ms overlap tolerance. One-to-one matching prevents a long detector alert
from receiving credit for multiple failures. Across 24 expected failure
intervals, 16 were matched to an observed interval. Mean matched onset lag was
613 ms and mean matched recovery lag was 371 ms.

## Interpretation

The high sample precision shows that wide particle clouds are a credible
failure signal for this run. The lower sample recall shows that many published
failures occur while the particle cloud remains compact, so particle spread is
not sufficient by itself. This measured gap is the target for the next detector
iteration, using additional robot-observable features without ground-truth or
label leakage.

This is an engineering baseline on published simulation data, not a safety
certification or a claim of performance on a physical robot.
