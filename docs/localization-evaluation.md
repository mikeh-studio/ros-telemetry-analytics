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
