# Contributing

## Local prerequisites and setup

Use Python 3.11+ and Node.js 22 (matching frontend CI). Java 17 and Maven are
needed only for Flink changes; Docker Compose is needed for service integration.
The ordinary Python, component and CLI contract tests do not need running ROS,
Docker, CUDA or GPU services.

From the repository root:

```bash
make setup                         # creates .venv; installs .[dev,demo]
npm --prefix demo/web ci
make lint
make test
npm --prefix demo/web test
make test-contract
npm --prefix demo/web run build
```

`make setup` includes demo dependencies because Python tests import the API and
Kafka adapters directly. For a separate batch-only environment, `pip install -e .`
installs the CLI; it is not sufficient for the full test suite.

## Checks by change

| Surface           | Checks                                                               | What they establish                                                                                               |
| ----------------- | -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Python            | `make format`, `make lint`, `make test`, `.venv/bin/python -m build` | Style, unit/contract behavior, coverage and package build                                                         |
| Frontend          | `npm --prefix demo/web test`, `npm --prefix demo/web run build`      | Components and production bundling                                                                                |
| Navigation report | `make test-contract`                                                 | Real Python CLI output accepted by the JS validator, decisions, bundled fixture fidelity and the maximum schedule |
| Flink             | `mvn --batch-mode -f streaming/flink-job/pom.xml verify`             | Java state and event-time contracts                                                                               |
| Services/browser  | Compose smoke and Playwright workflow below                          | Running service integration and rendered flows                                                                    |

The navigation contract runner uses `.venv/bin/python` when present; set `PYTHON`
to another installed interpreter if needed. It creates disposable reports in the
system temporary directory and removes them after each case. Simulator-labeled
test inputs exercise code paths; they do not authenticate simulator evidence.

## Browser and service checks

```bash
docker compose up -d --build
.venv/bin/python scripts/smoke_demo.py --timeout 240 --run-id local-clean-smoke
npm --prefix demo/web exec -- playwright install chromium
npm --prefix demo/web run test:e2e
```

The clean smoke runs a recorded mission and changes the active replay. The camera
dropout test is skipped unless `EXPECT_DROPOUT=1` is supplied after a completed
camera-dropout mission. See the exact clean/dropout sequence in
[CI](.github/workflows/ci.yml). Live ROS and simulator checks have separate
[setup and evidence requirements](docs/live-ros2.md).

For layout changes, inspect all four tabs, keyboard navigation, the upload dialog,
replay controls and a paired Navigation inspector at desktop and narrow widths.
Check prepared Recording/Localization views when compatible data is available;
empty-state checks do not cover populated evidence. Refresh relevant
[README screenshots](artifacts/README.md).

## Code ownership and fixtures

- `App.jsx` composes workspaces. `WorkbenchShell.jsx` owns the header and tabs;
  `useWorkspaceView.js` owns URL/preferences; `useWorkbenchState.js` owns replay,
  catalog, upload and readiness state.
- `TelemetryView.jsx`, `ReplayControls.jsx`, `TelemetryVisuals.jsx` and
  `UploadRecordingDialog.jsx` own presentation. Keep network operations in the
  controller and preserve hidden-panel state and effect cleanup when refactoring.
- Shared theme tokens live in `demo/web/src/styles/tokens.css`; shared foundations,
  shell and controls live in `styles/workbench.css`. Feature-specific recording
  and navigation layouts remain alongside their components. Extend the owning
  rule rather than adding another late-loaded override stylesheet.
- Python/JavaScript navigation validation serves different purposes. Python scores
  raw evidence; JavaScript validates saved display fields. Update both deliberately
  and run the cross-language contract check whenever the report changes.

Keep downloaded recordings and generated outputs in the ignored `data/` subfolders;
private notes and scratch reports belong in `.local/`. Do not commit either.
Tests use generated or redistributable fixtures. Ingestion changes need discovery,
reader, failure-isolation and idempotency coverage. Analytics changes need an edge
case showing the metric before and after the condition being tested.

Use the [examples index](examples/README.md) to distinguish reproducible inputs
from retained historical observations. Do not update old result files to imply
new validation; create a clearly identified result when rerunning an experiment.
