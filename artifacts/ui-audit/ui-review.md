# Robot Telemetry Flight Deck UI Review

Reviewed from the live UI on 2026-08-31 at normal desktop width and 200% zoom. This review is read-only; no application code was changed.

Resolution update: the P1/P2 findings were fixed after this review. The title lockup has an explicit 18 px gap and protected columns; operational labels now use a shared, larger legibility floor; readiness and connection state live in one stable header stack; related mission controls are grouped; and telemetry/localization hierarchy has more reading room. The P3 long-incident fixture remains follow-up polish.

## Overall assessment

The flight-deck direction is coherent and distinctive. The black canvas, condensed display type, mono operational labels, thin dividers, and restrained green status color give the interface a credible control-room character. The main weaknesses are spacing resilience and text legibility: several values are tuned for one large desktop composition and become either collision-prone or overly sparse as the viewport changes.

## Prioritized findings

### Resolved - Make the title-to-eyebrow spacing explicit

The H1 is visually collision-prone because it combines a `12px` top margin with a very compressed `.84` line-height. The font's glyph box can extend beyond that line box, so the apparent gap varies with font loading, zoom, and browser rendering. The first screenshot is just clear at the tested width, while the reported overlap is consistent with this CSS setup.

Recommended implementation:

- Make `.title-lockup` a small vertical grid with an explicit `16px` to `20px` gap.
- Reset the H1 margin to `0` so spacing has one owner.
- Raise the H1 line-height to roughly `.90` to `.94`; keep the two-line lockup and current letter spacing.
- Add a visual regression check for the title at desktop, the `1050px` breakpoint, and the narrow mobile breakpoint.

### Resolved P1 - Raise the microcopy legibility floor

Many operational labels are between `.55rem` and `.62rem`. At normal desktop zoom, readiness states, timeline ticks, table headings, trajectory legend labels, event labels, and footer copy are difficult to scan. Uppercase plus wide tracking reduces legibility further.

Recommended implementation:

- Establish a shared operational-label token around `0.68rem` to `0.72rem` with a minimum 1.3 line-height.
- Reserve `.58rem` only for genuinely tertiary details, not table headings or live state.
- Reduce tracking on the smallest labels from `.10em` to about `.06em` to `.08em`.
- Recheck muted text contrast after increasing size; screenshot review alone cannot establish WCAG compliance.

### Resolved P2 - Rebalance the command header across widths

At desktop width, the readiness row and connection mode occupy the far-right column while the title dominates the left, leaving a broad empty band. At 200% zoom, the header stacks cleanly but creates an oversized gap before readiness. The negative `margin-top` on `.header-state` makes this area especially brittle.

Recommended implementation:

- Remove the negative margin and put readiness plus connection mode in one self-contained right-side stack.
- Use a bounded gap between title, readiness, and mode instead of relying on the parent grid row gap.
- At the `1050px` breakpoint, use a smaller stacked gap so the header does not consume most of the first viewport.

### Resolved P2 - Bring mission controls and selectors into one control group

The transport controls sit at the far left while scenario and replay speed sit at the far right. The large empty middle makes related controls feel disconnected and slows scanning.

Recommended implementation:

- Constrain the timeline control row to its content or reduce `space-between` behavior.
- Keep selectors adjacent to transport controls with a clear 32px to 48px group gap.
- Preserve the existing column stack below `720px`, where the controls remain usable.

### Resolved P2 - Give telemetry and evaluation data more reading room

The telemetry table is structurally clear, but tiny headers, topic paths, and values make it feel compressed. In localization, the trajectory, scorecard, and event log are well organized, but the event descriptions and legend are difficult to read and the three panels compete equally for attention.

Recommended implementation:

- Increase table header and value sizes, add a little row height, and soften the prominence of repeated outlined `HEALTHY` pills.
- In localization, treat trajectory as primary, scorecard as secondary, and the event list as detail through width and type hierarchy.
- Increase event-row line-height and visually separate injected/expected time, detection time, lag, and recovery rather than placing them in one compact sentence.

### P3 - Protect the active-incident summary from long content

The zero state fits, but the narrow third mission-summary column leaves little tolerance for a longer anomaly name or robot-wide diagnostic message.

Recommended implementation:

- Give the incident column a practical minimum width or stack anomaly text below the count.
- Add a fixture with the longest supported incident name and topic path to visual tests.

## Strengths worth preserving

- The visual language is consistent from readiness through the localization scorecard.
- Primary states use restrained color semantics; green is not overused as decoration.
- The information sequence supports troubleshooting: mission state, time, transport, topic health, then labeled evaluation.
- Semantic headings, buttons, labels, table markup, status roles, and visible focus styles are already present in the source.
- The 200% layout stacks without visible horizontal clipping in the reviewed header and mission summary.

## Accessibility limits

This was a visual and structural review, not a full accessibility audit. Keyboard order, screen-reader announcements during live updates, reduced-motion behavior, touch target spacing, and measured color-contrast ratios still need direct testing.

## Suggested implementation order

1. Add a long-content visual regression fixture for the remaining P3 incident-summary finding.
2. Extend future accessibility QA to keyboard order, live announcements, reduced motion, touch targets, and measured contrast.

## Evidence

- `01-desktop-overview.jpeg` - full desktop composition.
- `02-localization-detail.jpeg` - telemetry, localization, collapsed detail rows, and footer.
- `03-responsive-200-percent.jpeg` - high-zoom stacked header and mission summary.
