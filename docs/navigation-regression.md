# Navigation regression evaluation

Compare a baseline and candidate using independent simulator evidence. The first
increment provides the offline scorer, paired statistics, a CLI, and adversarial
fixtures, plus a Workbench comparison view. **Live Gazebo pose/contact capture
and BARN orchestration remain unimplemented.** The old Nav2 mission JSON
is not a compatible input: it lacks independent pose and collision evidence.

## Try the synthetic fixture

```bash
.venv/bin/ros-telemetry evaluate-navigation \
  --input examples/navigation_regression_synthetic.json \
  --output data/evaluations/navigation/synthetic-first-run
```

The example intentionally introduces a candidate collision after reaching the goal.
Expect `REGRESSION` and exit code **1**. This is a synthetic software test, not a
measured navigation result. The output directory must not exist; choose a new
name for every execution. Outputs are the exact `input.json`, its SHA-256 in
`evaluation.json`, scored attempts and pairs, and a human-readable `report.md`.
Inputs are never rewritten; no ROS, Docker, Kafka or Flink connection is required.

| Exit code | Decision                                                                          |
| --------: | --------------------------------------------------------------------------------- |
|         0 | PASS: declared simulator evidence satisfies the frozen observed-suite gates       |
|         1 | REGRESSION: new paired collision or comparison beyond a frozen margin             |
|         2 | INVALID: missing scoring evidence, or an invalid input/IO error                   |
|         3 | INCONCLUSIVE: insufficient maps, uncertain comparison, or synthetic-only approval |

Malformed manifests fail before publication. A well-formed suite with missing or
invalid attempt evidence produces an INVALID report. Structural provenance errors
produce a CLI diagnostic rather than a partial comparison. Inputs are capped at 128 MiB, schedules at 10,000 pairs, and bootstrap work at
50 million map draws per metric. Duplicate JSON keys are rejected. Interrupted writes can
leave an incomplete output directory; retain it and use a fresh directory to retry.

## Input contract (schema_version 1)

See the committed synthetic example for an executable complete document.

| Field            | Meaning                                                                          |
| ---------------- | -------------------------------------------------------------------------------- |
| `suite_id`       | Stable, nonempty experiment identity                                             |
| `evidence_kind`  | `synthetic` or `simulator`; synthetic evidence cannot produce PASS               |
| `runtime_sha256` | Digest identifying the frozen simulator, robot, sensors and package manifest     |
| `configurations` | Exactly `baseline` and `candidate`, each with `config_sha256` and `git_revision` |
| `policy`         | Optional overrides of the defaults below, frozen before evaluation               |
| `scenarios`      | Entire expected schedule, including missing or failed attempts                   |
| `attempts`       | At most one run per scheduled scenario/seed/configuration                        |

Each scenario has `scenario_id`, nonnegative integer `seed`, `map_sha256`,
`scenario_sha256`, `start` and `goal`. Poses are `[x_m, y_m, yaw_rad]` in the same
fixed map frame. `scenario_sha256` should identify the complete scenario including
start/goal, seed, fault schedule and map. One scenario ID cannot name different
maps. Different IDs sharing a map digest remain a single statistical cluster.

Each attempt has a unique `run_id`, scenario ID/seed, `configuration` (`baseline`
or `candidate`), and the configuration, revision, scenario and runtime identity
fields matching the manifest. Retries belong in a separately identified suite;
duplicate attempts are rejected instead of selecting the best result.

After goal acceptance, record:

- `elapsed_s`: finite, nonnegative duration in **simulation time**.
- `termination`: `finished`, `timeout`, `crash`, or `harness_error`.
- `ground_truth`: ordered `{ "t": seconds, "pose": [x, y, yaw] }` observations
  from an independent simulator pose source, not AMCL or odometry.
- `contact_heartbeat_s`: continuous health observations from the obstacle-contact
  collector. Contact events alone cannot establish observation of zero collisions.
- `obstacle_contacts`: explicit list of `{ "t": seconds, "obstacle": "identity" }`.
  An empty list means observed zero; absent/null is unknown. The collector must
  exclude wheel-ground and internal robot contact without excluding obstacles.

Both evidence streams start at exactly zero, end at `elapsed_s`, are strictly
increasing, and have no gap over the configured limit. Start pose must match the
scenario within 1e-6 per coordinate. Before live collection, establish a realistic,
versioned start-validation tolerance from simulator measurements. Do not align
or repair a measured trajectory to pass this check.

`rejected` is a pre-execution outcome with elapsed time zero and absent or empty
pose, heartbeat and contact lists. It cannot conceal recorded execution evidence. A crash with complete evidence is a navigation failure. A crash with
incomplete scoring evidence remains INVALID; its original termination is retained
in `input.json`. Harness failures always invalidate evidence.

**Trust boundary:** matching hashes detects mismatches between supplied manifest
and attempt identities. It does not authenticate a JSON file, verify an external
image, or prove a collector is truthful. The future runner must retain the actual
configuration/package manifests and source recordings that those hashes identify.
Never relabel synthetic evidence as simulator evidence to obtain PASS.

## Scoring and comparisons

Defaults: position tolerance 0.25 m, yaw tolerance 0.25 rad, continuous goal hold
1 s, timeout 120 s, evidence gap at most 0.25 s. Arrival is the first sampled time
at which all observations during the hold are in tolerance. Samples do not prove
continuous occupancy between timestamps. Yaw errors wrap at ±π. A contact
anywhere in the captured attempt overrides arrival; a crash also remains a
failure. Unverified early termination is `goal_not_verified`. Timeout is measured
in simulation time, independent of the runner's future wall-clock watchdog.

Path length is the sum of planar distances between ground-truth samples over the
whole capture. It is descriptive; sampling, resets and teleport integrity must be
controlled by the future collector before using it as an acceptance metric.

The report includes complete outcome counts for each configuration, all scheduled
attempts and matched pairs. Missing attempts invalidate the comparison. It never
silently drops failed attempts from success comparisons.

- **Success difference:** candidate minus baseline success, averaged within maps,
  then equally across map digests. Failures remain in this denominator.
- **Time ratio:** candidate/baseline completion time for pairs where both succeed;
  mean log ratio within maps, then equal-map mean, exponentiated. This is a
  geometric mean, not the ratio of unpaired successful-run averages. The report
  exposes matched-success pair and map counts in JSON.
- **Uncertainty:** 5,000 paired map-cluster bootstrap draws, deterministic seed
  20261006, percentile 95% intervals. Seeds stay with their map. The minimum is
  20 independent maps for success and 20 with matched successes for approval.

A new observed collision against a known collision-free baseline pair is a
REGRESSION even in a small pilot. A success-loss interval entirely below -0.02
also fails when enough maps exist, even if there are no matched successes. Other
statistical decisions require enough maps for both metrics. PASS requires the
success interval's lower endpoint above -0.02 and the time-ratio interval's upper
endpoint below 1.10. A time interval entirely above 1.10 fails; overlap or exact
boundary contact is INCONCLUSIVE. These tolerances are proposed project policy.

Bootstrap intervals are conditional on the frozen suite. Identical observed
outcomes can yield degenerate intervals; even many collision-free runs cannot
establish zero risk on unseen environments or rare failures. The minimum-map
rule is a guard against tiny pilot approvals, not a statistical power guarantee.

## Next integration gate

1. Instrument the owned Jazzy/Gazebo sandbox with independent pose and contact
   evidence, retaining package versions and raw evidence. Validate true arrival,
   contact, crash and collector loss separately.
2. Extend the runner to reset the world and execute a frozen paired schedule.
   Use a separate wall-clock startup/stall watchdog. Preserve incomplete attempts.
3. Import pinned BARN maps and verify robot-footprint compatibility. Run a 60-attempt
   development pilot before freezing larger comparisons. This is BARN-derived
   evaluation unless official benchmark conditions are reproduced.
4. Connect richer capture evidence to the existing Workbench inspector. Keep TUHH
   detector evaluation and OpenLORIS pose evaluation as separate test tracks.

Dataset references: [BARN](https://arxiv.org/abs/2008.13315),
[TUHH](https://doi.org/10.15480/882.15836),
[OpenLORIS](https://lifelong-robotic-vision.github.io/dataset/scene.html).

## Workbench view

Open `http://localhost:3000/?view=navigation` after rebuilding the web service
(`docker compose up -d --build --no-deps web`). The Navigation tab displays the
bundled synthetic collision example, comparison metrics and selectable attempt
outcomes. It works independently of the selected ROS recording and API readiness.
Use **Import comparison** to inspect output from the CLI above; files are read
locally in the browser, with a 10 MiB / 5,000-pair limit. Both scheduled attempts
must be retained per pair, including invalid placeholders. The viewer validates display fields
but does not rerun scoring or authenticate the declared simulator provenance.
The current view does not launch missions, collect trajectories, or run BARN.

The redesigned view groups baseline/candidate evidence in one scenario row.
**Review regression** filters and opens the first matching pair; the inspector
shows both outcomes, the pair rule, available deltas and missing-data limits.
Wide screens use a split view; narrow panels use a full-width inspector with Back.
Filters describe pair changes and do not replace the evaluator's suite decision.
Aggregate-only regressions link to evaluation details. File imports remain
browser-local and do not persist after reload. Raw trajectories are not included.
