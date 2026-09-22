# Dataset evaluation and workbench scope

Implemented scope from [the research](ros-data-learning-plan.md): evaluate existing recordings, add small LILocBench/TUM comparisons, and expose explainable offline investigations.

## Delivered

- Seven real recordings with source identities, extraction coverage and reconciled previews.
- Three reviewed investigations: image usefulness versus delivery, reference-tracking gaps, and command/odometry disagreement.
- Versioned evidence, bounded interval APIs, shared recorded-time plots and source samples.
- Host inventory, parser regression checks and a duplicate-only cleanup script that defaults to a review receipt.
- One recording selection across replay, offline recording evidence and saved localization evaluation.

## Retained boundaries

Raw recordings are observations, not confirmed physical-failure labels. References remain evaluation context until clock/frame alignment is validated. Warehouse Run 17 is a synthetic timing demo. TUHH retains its existing simulation evaluation and label-conflict handling. Unique uploads, previous studies and failed experiments are preserved.

NTU VIRAL, ARCO downloads, GNSS/radar analyzers and additional localization algorithms remain later work. See [results, reproduction and limitations](recording-investigations.md).
