# Design QA — exec-5027 timeline-first console

> Historical review snapshot; findings describe the implementation at the time of review.
> Evidence paths below are relative to the repository root.

## Comparison target

- Source visual truth: `artifacts/design-qa/source-exec-5027.png`
- Browser-rendered implementation: `artifacts/design-qa/implementation-desktop.jpeg`
- Same-input comparison: `artifacts/design-qa/final-comparison.jpeg`
- Responsive evidence: `artifacts/design-qa/mobile-responsive-top.jpeg`
- Route and state: `http://localhost:3000`, completed clean replay, all five stack services ready, localization evaluation available
- Source pixels: 1487 x 1058
- Implementation pixels: 1487 x 768
- CSS viewport: approximately 1859 x 960 at 80% browser zoom; responsive check approximately 496 x 256 CSS px at 300% zoom
- Density normalization: both desktop artifacts were captured and compared at the same 1487 physical-pixel width without resampling. The source is taller; the implementation crop records the available browser viewport and does not stretch either artifact.

## Findings

No actionable P0, P1, or P2 findings remain.

- Fonts and typography: the implementation uses a narrow system sans stack with a monospaced data stack. The two-line uppercase title, compact technical labels, weights, line height, and tracking now follow the source hierarchy without wrapping the title into a third line.
- Spacing and layout rhythm: the mission summary, full-width timeline, controls, telemetry table, and three-column localization evaluation follow the source order and thin-divider structure. The implementation keeps slightly more breathing room around live controls so the real selectors remain usable.
- Colors and tokens: the background is pure black; primary text is off-white; dividers are translucent white; healthy/completed states and the completed timeline are green; estimate data is amber; missed events are red. No gradients, rounded cards, or decorative shadows remain.
- Image quality and asset fidelity: the visual target has no photographic or branded raster assets. Transport controls use Phosphor icons. The trajectory is the existing data-driven SVG visualization, not a decorative substitute, and displays the real public evaluation data.
- Copy and content: the mission, replay, telemetry, and evaluation labels remain product-specific and source-backed. Scenario and replay-speed selectors are intentional functional additions to the source mock.
- Accessibility and responsiveness: semantic buttons, labels, table markup, live status roles, focus outlines, and SVG alternative text remain present. At the 300% responsive check, readiness becomes two columns, mission health stacks cleanly, and timeline controls remain separated and usable without overlap.

## Comparison history

### Pass 1 — blocked

- [P2] The title wrapped to three lines, changing the source hierarchy.
- [P2] Extra heading height and the operational-detail row pushed localization below the comparable source crop.
- [P2] The completed timeline remained white instead of using the source's healthy green state.

Fixes made:

- Kept `Robot Telemetry` on one line and tuned the display scale.
- Collapsed section headings, reduced vertical spacing, and moved optional operational details after localization.
- Applied the healthy green token to the completed timeline progress and cursor.

### Pass 2 — passed

The final same-input comparison shows the two-line title, mission summary, green completed timeline, full telemetry table, and localization evaluation in the intended order. The real trajectory geometry and extra scenario selector are expected product-data differences rather than fidelity defects.

Focused-region comparison was not required after the final full-view pass: the target and implementation share the same physical width, and the title, transport icons, telemetry rows, trajectory, metrics, and event summary remain legible in `final-comparison.jpeg`. The responsive capture separately verifies the most failure-prone stacked header and readiness region.

### Post-audit header regression — passed

A follow-up browser review found that the first H1 line could overrun its grid column and touch the `Stack readiness` eyebrow at some viewport and zoom combinations. The title lockup now owns an explicit 18 px vertical gap, uses a safer 0.9 line height and bounded display size, and receives an equal protected desktop column. The command header stacks below 1320 px rather than compressing the title and readiness content together.

Fresh Chrome captures at 1440 x 900 and 1000 x 900 confirmed clear separation between the title, its eyebrow, and the readiness region. The narrower capture also confirmed that the stacked header, five readiness services, connection state, and mission summary remain free of clipping or overlap.

## Primary interactions and runtime checks

- Start, pause, resume, and restart button state contracts: covered by the eight passing Vitest interaction/state tests.
- End-to-end browser contract: Playwright targets the redesigned mission summary, telemetry table, robot-health summary, and expandable incident log rather than the retired card layout.
- Scenario selection and 1x/5x constraint: covered by Vitest; the live browser shows both selectors and current clean-mission state.
- Live data and readiness: browser verified five ready services, completed replay data, four healthy topics, and available localization evaluation.
- Responsive layout: browser verified at 300% zoom with no visible overlap or horizontal clipping in the title, readiness, mission summary, timeline, or transport controls.
- Header regression: Chrome verified the corrected title lockup at 1440 px and the stacked command header at 1000 px; both preserve explicit space around the H1 and readiness eyebrow.
- Runtime errors: no visible browser error state after the final reload; the web container and API health endpoint were ready.

## Follow-up polish

- [P3] A bundled condensed font could make cross-platform typography more deterministic; the current narrow system fallback matches the selected direction on the verified Mac browser.

final result: passed
