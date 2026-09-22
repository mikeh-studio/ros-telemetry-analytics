# Shared dataset workbench

Implemented. Choose one recording for all three investigation tabs; switching tabs never silently selects another dataset or starts a replay.

- **Telemetry Health:** runtime readiness plus replay controls and topic-delivery history. Browsing another dataset leaves the active replay running and hides its metrics from the new selection.
- **Recording Investigation:** prepared source evidence, reviewed cases, interval plots and previews. Works without Kafka/Flink.
- **Localization Investigation:** a separately identified saved evaluation. The API rejects mismatched or changed evaluation identities.

Each tab shows availability. Dataset support, prepared evidence and running services are distinct states; “Ready” does not mean fault-free. Upload remains global. Uploaded recordings require validation for replay and separate preparation for offline evidence.

The recording menu aligns to its trigger, supports keyboard selection and dismissal, and scrolls the catalog. About this recording holds provenance and catalog refresh. Monitored topics use unboxed names, full paths, health text, trends and grouped observed/expected rates; inspection exposes gap details. At narrow widths, topic rows stack and tab navigation scrolls.

Keep the original Barlow Condensed / IBM Plex Mono typography, monochrome surfaces, and restrained semantic status colors. See [setup and evidence contracts](recording-investigations.md).
