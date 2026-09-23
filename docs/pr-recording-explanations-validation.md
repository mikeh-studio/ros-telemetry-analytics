# Recording explanations: PR validation

Validated locally on 2026-09-22 against the implementation in this PR.

## Review and cleanup

- Reviewed detector provenance, conservative grouping, artifact publication and
  stale-evidence rejection, API pagination, and UI dataset/incident transitions.
- Fixed rebuild polling so a new completion callback cannot trigger another POST;
  a regression test checks one POST and delivery to the latest callback.
- Removed the redundant interval API branch and moved the event-identity import
  to module scope. Formatted changed frontend files and ran the Python formatter.
- Kept the README focused on use cases, setup, screenshots, and limitations;
  detailed contracts and operational behavior remain in the guides.
- Checked spacing across Telemetry, Recording, and Localization, including
  expanded evidence, pipeline, connection, operational, and upload panels.
  Replay controls wrap; pipeline status text and long topic paths stay inside
  their panels. Tabs retain equal widths and left alignment.

## Automated checks

| Check                                      | Result                              |
| ------------------------------------------ | ----------------------------------- |
| Ruff lint and formatting                   | Passed                              |
| Python suite                               | 276 passed; 91.06% package coverage |
| Frontend unit/interaction suite            | 63 passed                           |
| Production frontend build                  | Passed                              |
| Python wheel and source distribution build | Passed                              |
| Docker Compose configuration               | Passed                              |

The frontend suite includes selection/reset behavior, evidence navigation,
pagination, rebuild completion/failure, cancellation, and callback replacement.
The Python suite includes source/provenance reconciliation, grouping boundaries,
fallbacks, digest checks, publication failure, and targeted signals beyond the
normal display limit.

## Browser and data checks

The local browser review covers real prepared recordings and the completed
built-in replay. Phone (320px), tablet (800px), and desktop (1600px) layout checks
found no remaining overflow in the expanded panels inspected. This is a focused
layout and interaction review, not an exhaustive accessibility audit.

The offline local preview was checked with LILocBench Dynamics 0, including
opening the exact odometry angular-velocity plot from its evidence link with no
browser errors. Telemetry services were not started in that preview.

All seven recordings were rebuilt successfully from the final source. The
[final preparation check](../examples/recording_incidents_pr_validation.json)
reconciles 317,443 messages, 270 warnings, 261 incidents, and 96 verified previews.
All incident documents pass the JSON schema; domain detector event tables match
the initial explanation validation exactly.

The earlier [seven-recording source validation](../examples/incident_explanation_validation_20260922_b031c10089ab4ed3b7477ac75cf8011c.json)
retains detector-parity and case measurements from the initial implementation.

## Limits

The full clean-stack replay/oracle/dropout workflow and browser regression suite
run in PR CI. Local browser checks do not replace those gates. This change adds
no physical-robot validation or causal ground truth. Rebuild jobs assume the
single-worker local API; uploads still require separate registration/preparation
for offline explanations.

## Recording header and replay layout

The selected design uses the available header width, with recording metadata on
the right at desktop sizes. Tabs retain equal widths in a compact left-aligned
group; their divider spans the content area. Replay settings and actions sit
beneath the heading with 44px controls and a 40px gap below the tabs.

The previous checks measured button boxes but missed their overflowing text.
The replay action now has a dedicated class, intrinsic width and a single-line
label, removing the inherited 42px icon-button width. The recording picker also
no longer has a fixed 380px width.

Browser checks passed at 320, 390, approximately 768 and 1024, 1440, and 1920 CSS
pixels: no horizontal overflow, equal tab widths, action text inside its button,
and aligned desktop controls. Start, pause and resume were exercised on the
built-in recording. All 63 frontend tests and the production build passed.
The equivalent automated browser regression was extended; its execution remains
a PR CI gate. See [design QA](../design-qa.md) for comparison and capture details.

See the [desktop overview](../artifacts/workbench-review/option-one-desktop.jpg).

## Compose smoke startup regression

The failed Nav2 browser check exposed a startup ordering issue: a snapshot could
arrive before readiness, causing the pipeline fault panel to open for an unknown
initial connection state. Readiness now distinguishes pending initialization from
a confirmed failure. Health stays unconfirmed while loading; real readiness
failures, SSE errors and gateway faults still open the panel.

Four unit cases cover both initial response orders and explicit readiness/network
failures. A browser regression deliberately holds readiness until after the
snapshot. Existing fault expansion and manual-collapse assertions remain intact.
The signal buttons use exact accessible-name selectors to distinguish selection
from inspection actions. Locally, 67 frontend tests, the production build and all
three signal-group browser tests pass.

[CI run 35820888711](https://github.com/mikeh-studio/ros-telemetry-analytics/actions/runs/35820888711)
passed all jobs on commit `391c9a9`, including the full Compose replay, oracle,
dropout, and browser checks.
