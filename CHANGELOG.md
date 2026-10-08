# Changelog

All notable changes to this project are documented here.

## Unreleased

## 0.2.0 - 2026-10-07

Upgrade notes:

- The Compose project is now `ros-telemetry-analytics` (was
  `robot-telemetry-flight-deck`), so Docker creates new containers and volumes.
  Follow the migration steps below before starting the renamed stack.
- Playwright variables are renamed: `FLIGHT_DECK_BASE_URL` to `WORKBENCH_BASE_URL`
  and `FLIGHT_DECK_BROWSER` to `WORKBENCH_BROWSER`.
- Saved experiment results moved from `examples/` to `examples/results/`.
- The ARCO and OpenLORIS dataset profiles and catalog entries were removed.

For an existing Compose installation:

1. Stop and remove the old project's containers to free ports 3000, 8000 and
   8081, while preserving its volumes:

   ```bash
   docker compose -p robot-telemetry-flight-deck down --remove-orphans
   ```

   Do not add `-v`. A plain `docker compose down` now targets the renamed project
   and will not stop the old stack.
2. Preserve any needed old volume data. Uploaded recordings in
   `robot-telemetry-flight-deck_dataset-uploads` are not migrated automatically.
   Copy them into `ros-telemetry-analytics_dataset-uploads` before starting the
   new stack, or retain the originals for re-upload afterward.
3. Start the new stack with `docker compose up --build -d` (include the same
   live/simulation overlays if used), re-upload recordings if needed, and verify
   the data you want to keep is available.
4. Only after verification, optionally list the old project's volumes with
   `docker volume ls --filter label=com.docker.compose.project=robot-telemetry-flight-deck`
   and remove selected, unneeded volumes with `docker volume rm <volume-name>`.
   Volume removal permanently deletes their contents.

Changes:

- Corrected SECURITY.md: supported payloads are deserialized; documented the
  trust model and the local-only scope of the Compose stack.
- Finished the Flight Deck to ROS Workbench rename across services, tests and docs.
- Consolidated documentation: experiment results, evaluation rules and remaining
  gaps live in the reliability case study; the dataset audit is part of the
  recording guide; development plans and PR records were removed.
- Added the four-workspace ROS Workbench for replay telemetry, prepared recording
  investigations, localization evaluation and offline navigation comparisons.
- Added deterministic incident explanations, source evidence inspection and
  explicit preparation/availability states.
- Added paired navigation scoring, collision gates (including rejected baselines),
  map-cluster uncertainty, bounded imports and contextual input diagnostics.
  Live navigation evidence collection remains unimplemented.
- Unified workspace layout and extracted shell, replay state, controls, upload
  dialog and Telemetry presentation into focused modules; consolidated shared
  styles and removed obsolete launch controls. Phone tabs use two equal columns
  to keep labels readable.
- Aligned developer installation with CI, added CLI-to-viewer compatibility checks,
  refreshed onboarding screenshots and indexed runnable versus historical examples.
- Updated Vitest and vulnerable transitive frontend dependencies.
- Added configurable timestamp-pair relationships with per-pair thresholds,
  required/optional counterpart handling, and `relationship_health.parquet`.
- Preserved automatic left/right stereo discovery and projected configured
  stereo relationships into the existing VSLAM output.
- Added selective payload extraction and normalized records for odometry, IMU,
  velocity commands, transforms, diagnostics, and image features.
- Added deterministic domain metrics, time-bounded anomaly events, embedded bag
  summaries, and shareable per-bag Markdown reports with analyzer coverage and
  concrete data-health findings.

## 0.1.0 - 2026-07-09

- Renamed the project to ROS Telemetry Analytics to reflect its generic ROS1
  and ROS2 bag support.
- Added canonical discovery for ROS1 bags, ROS2 directories, DB3, and MCAP.
- Added streaming message indexes and per-bag atomic output publication.
- Added configurable topic-health, continuity, and stereo-timing analysis.
- Added source fingerprint skips, batch failure isolation, and run reports.
- Hardened asset downloads and archive extraction.
- Added package metadata, CLI, CI, coverage, security, and contribution docs.
- Included analytics configuration in cache invalidation.
- Pinned NVIDIA asset versions and checksums.
- Added ROS2 MCAP stereo integration coverage and package-build CI checks.
- Made empty, frozen, and missing sensor streams explicit health failures.
- Corrected nearest-frame pairing and documented bag log-time semantics.
- Added interrupted-publication recovery, stale-output reconciliation, and
  complete fail-fast manifests.
- Added locked, size-bounded asset downloads and atomic extraction recovery.
