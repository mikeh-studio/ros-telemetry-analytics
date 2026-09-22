# Workbench design decisions

The review found oversized dataset/scenario cards, competing controls, and inconsistent spacing. The approved direction keeps the original SpaceX-inspired monochrome styling and fonts.

Implemented:

- One shared recording context, with upload in the header and provenance behind a disclosure.
- Compact replay controls; fault injection appears only for the controlled demo.
- Content-sized tabs with equal gaps, icons and consistent availability text.
- A padded recording menu aligned to its trigger.
- Simple topic rows with full ROS paths, inline trends and secondary measurements in inspection details.

The mockups guide hierarchy rather than scientific content: live charts retain real window boundaries, missing/partial samples and per-topic scales. Sensor health and reference-stream coverage must not be conflated. See [shared behavior](shared-dataset-workbench-plan.md) and [QA](../design-qa.md).
