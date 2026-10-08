# Examples and saved results

The top level holds inputs you can run and sample outputs. [`results/`](results/)
holds saved experiment results: each describes the run that produced it, not the
current checkout or robot performance. Keep new reruns in the ignored `data/`
directory.

## Runnable fixture

| Input                                                                        | Purpose and expected outcome                                                                                               | Instructions                                                                   |
| ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| [navigation_regression_synthetic.json](navigation_regression_synthetic.json) | Synthetic paired evidence; a candidate collision after arrival produces REGRESSION, exit 1. No measured robot performance. | [Navigation guide](../docs/navigation-regression.md#try-the-synthetic-fixture) |

The Workbench's bundled [navigation evaluation](../demo/web/src/examples/navigation-synthetic.json)
is derived from that exact file. `make test-contract` checks the CLI output against
the bundled report, including its input digest. To regenerate it, run the CLI into
a new output directory and copy the resulting `evaluation.json` after reviewing
the decision. Do not change the input's formatting without regenerating its digest.

## Notebooks and sample reports

| Files                                                                                                      | Purpose / inputs required                                                                                                                            |
| ---------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| [dataset_audit.ipynb](dataset_audit.ipynb)                                                                 | Inspect dataset inventory and source-quality evidence; see [dataset audit](../docs/recording-investigations.md#dataset-audit). Downloaded recordings are not bundled. |
| [localization_investigation.ipynb](localization_investigation.ipynb)                                       | Explore saved localization evaluation; see [localization guide](../docs/localization-evaluation.md).                                                 |
| [sample_report.md](sample_report.md), [sample_domain_report.md](sample_domain_report.md)                   | Examples of generated batch reports, not current dataset analysis. See [bag analysis](../docs/bag-analysis.md).                                      |
| [sample_localization_eval.md](sample_localization_eval.md), [localization_study.md](localization_study.md) | Retained detector evaluation/report examples. Interpret with the source, thresholds and matching policy in the report.                               |

## Saved results (`results/`)

Preserve the run IDs, source references, policy and limitations inside these files.
Some records have no explicit capture date; do not infer one or treat their old
check counts as current. The linked guide supplies methodology and reproduction
commands where available.

| Files                                                                                                                                                                                                                                                                                                                  | Evidence family / methodology                                                                                                                                                                                            |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [dataset_audit_results.json](results/dataset_audit_results.json)                                                                                                                                                                                                                                                               | [Dataset inventory and quality audit](../docs/recording-investigations.md#dataset-audit)                                                                                                                                                  |
| [localization_study_results.json](results/localization_study_results.json)                                                                                                                                                                                                                                                     | [Offline localization detector study](../docs/localization-evaluation.md)                                                                                                                                                |
| [live_ros2_results.json](results/live_ros2_results.json), [qos_results.json](results/qos_results.json), [transport_fault_results.json](results/transport_fault_results.json)                                                                                                                                                                   | [Gateway, QoS and transport experiments](../docs/live-ros2.md)                                                                                                                                                           |
| [nav2_telemetry_results.json](results/nav2_telemetry_results.json), [nav2_localization_fault_results.json](results/nav2_localization_fault_results.json)                                                                                                                                                                               | [Nav2 telemetry and localization fault experiments](../docs/live-ros2.md); these are not compatible navigation-regression inputs.                                                                                        |
| [edge_recovery_results.json](results/edge_recovery_results.json), [fleet_isolation_results.json](results/fleet_isolation_results.json), [flink_restart_results.json](results/flink_restart_results.json), [projection_restart_results.json](results/projection_restart_results.json), [reliability_suite_results.json](results/reliability_suite_results.json) | [Reliability experiments](../docs/reliability-case-study.md)                                                                                      |
| [signal_projection_results.json](results/signal_projection_results.json), [trajectory_projection_results.json](results/trajectory_projection_results.json)                                                                                                                                                                             | [Signal and trajectory projection checks](../docs/live-ros2.md)                                                                                                                                                          |
| [browser_review_results.json](results/browser_review_results.json), [incident_explanation_validation_20260922_b031c10089ab4ed3b7477ac75cf8011c.json](results/incident_explanation_validation_20260922_b031c10089ab4ed3b7477ac75cf8011c.json)         | Rendered incident view ([case study](../docs/reliability-case-study.md)) and incident-explanation validation ([recording guide](../docs/recording-investigations.md#generated-incident-explanations)) |
