# Workbench UI validation

Scope: shared recording context, tab availability, recording menu and monitored topics.

- Original Barlow Condensed / IBM Plex Mono fonts and monochrome design retained.
- Menu and trigger measured 440 CSS px with matching edges and an 8 px gap.
- Topic names and inspection arrows have no boxes; long paths remain within their rows.
- Rates retain recorded data, per-topic axes and partial-window semantics. Gap details are available on inspection; unknown windows must not show the latest gap as a substitute.
- Browser checks covered recording selection, Escape dismissal, source inspection and no document overflow at 947 and 625 CSS px. The narrow capture had a compositor scaling artifact; DOM geometry supplemented that check.
- Unit tests cover keyboard navigation, outside dismissal, dataset isolation and stale responses. Browser error log was empty.

Evidence: [recording menu](artifacts/workbench-review/recording-picker.png), [topic rows](artifacts/workbench-review/topics.png). Captures are 929 × 1009 pixels at a 947 × 1029 CSS viewport and show TUM VI Room 4 after replay. The menu capture includes the existing inverted hover state.

Earlier P2 issue: generic button rules restored topic boxes and pushed inspection arrows out of bounds. Corrected specificity and recaptured both regions. The selected mock and both captures were reviewed together; the existing header, tabs and replay controls remain between the scoped regions. Charts keep real scales rather than decorative mock sparklines.

Follow-up: a shared chart time axis could reduce repetition. Full accessibility certification and the clean-stack CI browser suite are separate checks.

final result: passed
