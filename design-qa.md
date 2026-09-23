# Recording header and replay layout QA

final result: passed

Scope: implement the selected first design from the latest three-option set.

## Visual evidence

- Source: `artifacts/workbench-review/option-one-target.png` (1774 × 887).
- Normalized source: `artifacts/workbench-review/option-one-target-normalized.jpg` (1440 × 720).
- Browser implementation: `artifacts/workbench-review/option-one-desktop-full.jpg` (1776 × 2754), with the reviewed header/replay crop in `option-one-desktop.jpg` (1440 × 720).
- Measurements: `artifacts/workbench-review/option-one-responsive.json`.
- State: built-in Warehouse Run 17, completed, Telemetry selected, details closed, 1× speed.
- Desktop CSS viewport: 1440 × 900. Browser reports devicePixelRatio 0.8; viewport-only captures clipped the right side. Full-page capture included the entire content width and was normalized to 1440px for comparison. The scrollbar reduces the raw content width slightly.

The normalized target and implementation were opened together in the same comparison input. The header and replay region are readable at this size; a separate close-up was unnecessary. Responsive checks are recorded in the measurements file; mobile screenshots are omitted from the documentation.

## Comparison history

1. Initial implementation: control grouping was correct, but the toolbar was noticeably narrower than the chosen image. Increased the fault selector, segmented speed control and primary action widths, and made both field labels uppercase. No behavior changes.
2. Recaptured the final implementation and repeated the paired comparison. No remaining actionable P0/P1/P2 differences in the scoped regions.

## Required fidelity surfaces

- Typography: existing Barlow Condensed and IBM Plex Mono retained. Action labels remain on one line inside their buttons. Long recording names wrap on phones.
- Spacing: header uses available width; description and facts share the desktop row. Tabs remain equal and compact, with a full-width divider. Replay begins 40px below that divider. Controls align at desktop sizes and wrap on phones.
- Colors: black surface, off-white filled primary action, muted gray text/rules and green completion state match the selected direction.
- Assets: existing Phosphor icons retained; no raster imagery is needed for these components.
- Content: real dataset names, descriptions, durations and topic counts remain data-driven. The mock's manually inserted description line break is intentionally not hard-coded.

Minor retained differences: the existing rule above the tabs remains, and tabs use the existing compact 220px desktop width instead of the mock's slightly wider rendering. These do not change the selected grouping or responsive behavior.

## Validation

- Browser assertions passed at 320, 390, approximately 768 and 1024, 1440 and 1920 CSS pixels. No horizontal overflow; equal tab widths; 44px control heights; action labels fully inside button borders; 40px separation from tabs. Wide header/picker growth was measured.
- Checked completed, running and paused controls, including Pause, Resume and Restart label containment at 320px. Started the demo, paused, resumed and observed completion.
- Opened/closed recording details and picker, dismissed the menu with Escape, and selected TUM VI Room 4 to check the toolbar without fault injection.
- Browser console error log was empty at the final interaction check.
- 63 frontend unit tests and production build passed. The automated browser regression was extended to include text containment and header growth; the full CLI browser suite is left to PR CI. Interactive checks used the in-app browser.

No open design questions. Full accessibility certification and every recording/state combination are outside this focused validation.
