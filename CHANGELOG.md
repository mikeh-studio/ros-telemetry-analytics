# Changelog

All notable changes to this project are documented here.

## Unreleased

- Added configurable timestamp-pair relationships with per-pair thresholds,
  required/optional counterpart handling, and `relationship_health.parquet`.
- Preserved automatic left/right stereo discovery and projected configured
  stereo relationships into the existing VSLAM output.

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
