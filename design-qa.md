# Mission launch bar — version 1 QA

Source visual truth: `/Users/mikeh/.codex/generated_images/01a09e41-9a4f-7161-864b-baacb35106c3/exec-eec5c85d-af5d-4864-89ee-217f5de8a594.png` (first displayed mission-setup prototype, selected by user).

Implementation: http://localhost:3000/.

Evidence: `/private/tmp/ros-launch-qa/desktop-ready.png`, `/private/tmp/ros-launch-qa/desktop-completed.png`, `/private/tmp/ros-launch-qa/mobile-before.png`, `/private/tmp/ros-launch-qa/mobile-final.png`.

Desktop viewport 1440 × 1024 CSS px; mobile 390 × 844. Browser capture excludes its scrollbar. Source and implementation were displayed together in one tool call for proportional content-region comparison; generated source raster density is not treated as CSS sizing. The source shows Warehouse Run 17 ready to start; the same ready state was inspected with TUM VI, while Warehouse was inspected with its existing completed run. Actual source descriptions, elapsed state and controls intentionally follow the loaded data. No recorded state was reset to fabricate a match.

## Findings and comparison history

- Initial desktop comparison: source/configuration/action grouping matches the selected design. A large amber text button replaces the detached play square. Dataset metadata and description remain next to selection; the duplicate mission name is removed.
- P2 mobile: Dataset and Add Data sharing a row clipped the selected recording name. Fixed by placing Add Data beside the label and giving the selector the full width. The final mobile capture shows the full TUM VI name and the large Start Mission action without horizontal overflow.
- Post-fix result: no actionable P0/P1/P2 layout findings for the changed setup region.

## Required fidelity surfaces

- Typography: existing bundled Barlow Condensed and IBM Plex Mono retained; condensed headings and readable form text follow the selected hierarchy.
- Spacing: three desktop groups separated by thin vertical rules; setup stacks in reading order on mobile. Existing app gutters and compact header retained.
- Colors: existing black, off-white and gray tokens; amber primary action and selection; runtime status colors remain data-driven.
- Assets: no raster illustrations needed. Existing Phosphor transport icons retained for secondary controls; primary action is real accessible button text.
- Copy: mission setup instruction matches prototype. Dataset description and size are sourced from the catalog. Live sessions keep their gateway-managed explanation and restrictions.

## Intentional differences and limits

The full monitoring table, stack readiness, robot status and incident evidence remain available, including columns omitted by the simplified mockup. This preserves monitoring coverage. The diagram-like empty monitor in the prototype does not replace real completed-run results. The scope is setup layout; this is not a new ROS/Nav2 or backend validation run.

## Verification

- 40 frontend tests passed, including dataset-to-start request, lifecycle states and live-session restrictions.
- Production build and git diff --check passed, including after the CSS adjustment.
- Browser verified desktop completed/ready states, dataset selection, unavailable scenario for TUM VI, Add Data open/close and mobile layout.
- Browser warning/error log empty during check; no horizontal page overflow at inspected desktop/mobile widths.
- Viewport override reset; original TUM VI dataset selection restored; local preview left running.

No remaining required implementation items. No additional raster assets or publish steps.

final result: passed

---

# Compact workspace header design QA

Source visual truth: `/Users/mikeh/.codex/generated_images/01a09e41-9a4f-7161-864b-baacb35106c3/exec-193ba0fe-04fa-4660-8656-80bc635d50f5.png` — first displayed prototype selected by the user.

Implementation: http://localhost:3000/ (rebuilt local web container).

Evidence:
- `/private/tmp/flight-deck-header-qa/desktop.png`
- `/private/tmp/flight-deck-header-qa/header.png`
- `/private/tmp/flight-deck-header-qa/desktop-health.png`
- `/private/tmp/flight-deck-header-qa/mobile-investigation.png`
- `/private/tmp/flight-deck-header-qa/mobile-health.png`

## Comparison

Desktop CSS viewport: 1219 × 900; mobile: 390 × 844. The in-app browser excludes the scrollbar in its rendered capture; desktop header clip is 1204 × 290. The source raster is 2164 × 727. These are not identical-density screenshots: the generated reference includes black canvas padding above and below the component. Comparison aligned the content regions proportionally, ignoring that outer padding and raster density. No pixel-perfect claim is made. The reference and rendered header were opened together in the same comparison tool call; the full desktop screen was also inspected to check the transition into the existing investigation workspace. The focused header crop made all navigation, title and metadata text readable.

State: Localization Investigation selected; TUHH evaluation loaded; API connected; evaluation disclosure collapsed. Recording duration is the real API value 03:32.55. Robot Health and mobile states were inspected separately.

## Findings and fidelity surfaces

No actionable P0/P1/P2 differences in the inspected states.

- Typography: existing bundled Barlow Condensed and IBM Plex Mono preserved. Compact 30px identity and heading, 20px desktop navigation, 14px subtitle and 12px metadata follow the selected hierarchy. Mobile navigation wraps without hiding either view.
- Spacing: brand, views and connection share one desktop row; one heading, explanatory sentence and recording context follow below. Existing app gutters are retained; the generated mock's unused outer black padding is intentionally omitted. On mobile the tabs occupy a second row and metadata wraps naturally.
- Colors: existing black base, off-white text, gray separators and connection green preserved; amber selection and focus treatment remain visible.
- Assets: target contains editable UI text, separators and a standard connection indicator only. No raster illustrations or custom logo assets were implied or substituted.
- Content: recording name and duration use the loaded evaluation. Missing duration remains Unavailable. The independent recording clock is explicit. Detector version, configuration and source filenames remain accessible in the existing evaluation disclosure. Robot Health retains its own recorded/live source label.

## Verification

- All 40 frontend tests passed, including keyboard tab switching and investigation behavior.
- Production build and git diff --check passed.
- In-app browser: switched tabs with Home and ArrowRight, confirmed focus and selected panel, opened and closed evaluation details, verified configuration and source files remain present.
- No horizontal page overflow at 1219px or 390px in inspected states.
- Browser error/warning log was empty during this check.
- Both desktop and mobile layouts inspected; temporary viewport override reset and investigation left open.

## Comparison history

First rendered comparison passed with no substantive visual corrections required. Subsequent mobile and alternate-view checks found no blocking layout problems. Tests cover existing playback behavior; this header pass did not perform a new live ROS/Nav2 run or backend suite.

## Follow-up polish

None required for this scope. This is targeted visual and interaction QA, not an accessibility compliance audit.

final result: passed

---

## Prior design QA (retained)

# Mission sequence design QA

Selected target: Version 1, replacing Version 2 at the user's request.

Source: `/Users/mikeh/.codex/generated_images/01a088ec-47d9-7a10-883f-856abb4aa40e/exec-a39514b8-30e8-4fdb-9003-fceffe9546b8.png` (1487 × 1058 pixels).

Final implementation: `/private/tmp/flight-deck-layout-research/04-mission-sequence-final.png` (desktop 1440 × 1024 CSS viewport; capture 1425 × 1013 pixels).

The source and implementation were opened together at native aspect ratios for a structural comparison. Source data are an illustrative Warehouse run; the currently selected real run is TUM RGB-D, with seven topics and four recovered incidents. That data and topic-count difference is intentional. No synthetic chart values were introduced and no new replay was started in this pass.

## Comparison and fixes

- Removed the left setup rail and returned to a full-width mission sequence.
- Dataset and Add data occupy the top row; mission identity and replay setup share the next desktop row.
- Readiness and mission timeline precede robot health and incident results.
- Replaced large topic lanes with a semantic table: topic, health, rate history, observed, expected, and window max gap. Gaps use the same inspected window as observed rate, not an unlabeled whole-run maximum.
- Collapsed time inspection and topic detail by default to reduce permanent control clutter.
- First comparison showed sparkline rows could be more compact; reduced chart height from 70px to 54px and recaptured. The first four actual topics now fit in the desktop entry view.
- Retained original fonts, black background, square controls, thin separators, real history, revision handling, and missing/partial-window behavior.

## Verification

- 20 frontend tests passed after table conversion.
- Final production build passed; git diff --check passed.
- Browser: expanded Inspect time, selected 00:15, and verified observed rates and max gaps changed together. Returned to latest values and collapsed inspection.
- Desktop 1440 × 1024 and mobile 390 × 844 inspected. On mobile, each table row stacks its chart and values without observed horizontal overflow.
- Existing backend history behavior was preserved; backend code was not changed in this layout pass.

## Limits

This is layout and targeted interaction verification, not a fresh end-to-end ROS evaluation or accessibility compliance audit. Browser console collection was not performed. Actual charts intentionally differ from the illustrative source. More than four topics require scrolling. The inspection cursor reads retained window endpoints and does not seek playback.

No remaining actionable P0/P1/P2 layout issues in inspected states.

final result: passed

## 2026-09-14 — Inline mission setup and telemetry naming

- Source visual truth: `/Users/mikeh/.codex/generated_images/01a09e41-9a4f-7161-864b-baacb35106c3/exec-78986732-9818-4779-a520-fe53080e7e3e.png` (second displayed alternative, 2039×771 pixels; intended 968×366 CSS frame).
- Implementation screenshots: `/tmp/ros-inline-desktop.png` (953×837 pixels), `/tmp/ros-inline-mobile.png` (375×812 pixels).
- Requested browser viewports: desktop 968×850; mobile 390×844. Browser capture excludes its reserved scrollbar/frame area. Reference visually normalized to desktop content width for comparison; implementation includes monitoring content below the source crop.
- State: TUM VI Room 4 512, completed recording, clean scenario, 5× selected, API connected. No mission restarted for this review.
- Full-view comparison: source-first desktop columns, underlined dataset/scenario controls, segmented speed, amber action and readiness underneath are preserved. Mobile stacks these in source/configuration/action order with no horizontal document overflow (scrollWidth375, innerWidth390).
- Focused comparison: inspected mission setup controls, dataset disclosure, and import dialog directly in browser screenshots. Radio selection changes, Details expansion/collapse, and import open/close verified. Mobile dialog fits viewport.
- Typography: existing bundled Barlow Condensed and IBM Plex Mono retained; readable 13–16px setup labels/values. Source raster typography was used as direction, not stretched into UI.
- Spacing/layout: 40px desktop selectors and primary action; mobile44px targets. Lower visual weight, one separator between source and configuration. Header and downstream content retain existing app spacing.
- Colors/tokens: existing black, gray, white and amber tokens; selected radio charcoal. No new decorative palette.
- Image quality/assets: no raster content required; real native selects, radio inputs, existing UI typography/icons rather than screenshot-as-UI.
- Copy: user-authorized Telemetry Health, Monitored Topics, Telemetry status, Topic column, Total monitored topics; actual robot identity remains. Unknown identity uses Unknown source. Import recording replaces Add data. Dataset description is preserved behind Details rather than hardcoding mock sensor-rate metadata.
- Comparison history: initial render exposed one residual Robot signal table heading; corrected to Topic and confirmed in final browser accessibility state. Related docs/test labels updated.
- Findings: no remaining actionable P0/P1/P2 findings for this change.
- Validation: 41 frontend tests passed, including speed selection/reset to1× for fault injection and existing live controls; production build passed; git diff --check passed. Browser error log empty. Native radio keyboard semantics retained; full assistive-technology audit not performed. Actual upload and fresh live Nav2 run not exercised.
- Implementation checklist: selected layout implemented; import copy updated; generic robot labels renamed; desktop/mobile interactions reviewed; browser viewport restored.
- Follow-up polish: none required for selected scope.
- final result: passed
