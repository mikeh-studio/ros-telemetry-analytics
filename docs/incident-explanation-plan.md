# Deterministic incident explanations

Status: implemented and locally validated on 2026-09-22. See the
[usage guide and validation evidence](recording-investigations.md#generated-incident-explanations).
The design below records the delivered first-release scope and deferred follow-ups.

Prepared on 2026-09-22 against local commit `20a0b27` on `codex/dataset-investigations`. This is a map of the inspected checkout, not a claim about the deployed application or the current remote branch.

## Outcome and scope

For a prepared robot recording, ROS Workbench should identify related warnings, show what measurements support them, explain the limits of the evidence, and suggest the next useful check. The same source, analysis configuration, and explanation rules must produce the same incident content.

The first release belongs in **Recording**. It runs during offline preparation and requires no LLM, model credentials, Kafka, Flink, or replay. It uses registered, prepared recordings supported by the existing investigation workflow. Uploading a recording will still require separate preparation before explanations become available.

The first three explanation families are:

1. Image brightness/sharpness warnings, with delivery context when measurable.
2. Recorded delivery gaps, distinguishing reference coverage from sensor delivery.
3. Command/odometry disagreement, with the exact matching policy and frame limitations.

Other event types remain visible with a factual fallback. This release does not claim physical root causes, assign causal probabilities, automatically label reference intervals as ground truth, or change detector thresholds to make demonstrations look better.

Live incident explanations, automatic upload preparation, automatic healthy-baseline selection, comparisons across runs, incident priority scoring, and export are separate follow-ups. In particular, the live panel's event-time/recovery revisions and limited signal retention need their own adapter; offline evidence must not be silently reused as live evidence.

## Pre-implementation baseline and planned updates

| Area | Current behavior | Required update |
| --- | --- | --- |
| `src/ros_telemetry_analytics/domain_analysis.py` | Emits typed anomaly rows. `_group_samples()` already groups nearby failing samples within individual detectors. Some counts and explanation context exist only in `detail` text. | Preserve detector semantics; emit structured provenance for supported events, including sample counts, conditions, and comparison inputs. Do not parse prose to recover evidence. |
| `src/ros_telemetry_analytics/investigations.py` | Prepares source-bound bundles; `event_records()` combines domain warnings with recorded/reference gaps. API payloads cap events at 200. | Normalize and identify the complete event set once during preparation; build incidents before display limits; publish explanation artifacts with the bundle. |
| `configs/recording_cases.yaml` and `scripts/curate_investigations.py` | Three manually reviewed cases supply observation, conclusion, next check, and limits. Annotations are tied to an analysis ID. | Keep these as separately labeled reviewed notes and acceptance examples. Generated explanations must not copy case prose or depend on case IDs. |
| `demo/api/recording_investigation.py` | Read-only metadata and bounded interval endpoints, with analysis identity checks and cached intervals. | Add paginated incident summaries and exact incident detail; validate identity and references before serving. |
| `demo/web/src/RecordingInvestigation.jsx` | Reviewed-case selector, three synchronized plots, previews, raw event table, and provenance. | Add generated-incident selection and an explanation panel connected to the same plots, cursor, and evidence. |
| `demo/web/src/IncidentDetail.jsx` | Live/replay panel groups revisions by `anomaly_id`, uses fixed observation strings, and shows retained signals. | No first-release behavior change. This is a separate incident model, not an offline grouping implementation to reuse directly. |

The current command analyzer chooses the odometry topic with the most records and matches commands to the nearest recorded-time sample within the configured window. Its `command_without_motion` event exposes a maximum commanded speed, not a measured tracking-error magnitude. Explanations must name these semantics, including that a nearest match can precede the command. They must not describe this check as proof of response delay or physical immobility.

## Processing flow

```text
Recording + existing analysis profile
  -> existing extraction and deterministic detectors
  -> complete normalized events + structured detector provenance
  -> conservative incident grouping
  -> measurement and coverage checks for explanation rules
  -> predefined explanation templates + evidence references
  -> validated, versioned bundle artifacts
  -> read-only API
  -> incident list, explanation panel, linked plots and samples
```

Detection, grouping, and explanation are distinct operations. Grouping changes presentation, not detector outcomes. An incident retains its original member events. Context observations can support inspection without becoming warnings or group members.

## 1. Define the evidence and explanation contract

Add `schemas/recording-incidents-v1.schema.json` and typed Python records in a new `src/ros_telemetry_analytics/incident_explanations.py` module. Keep grouping helpers in a new `src/ros_telemetry_analytics/incident_grouping.py` module. Validate semantic invariants in Python as well as the JSON shape in contract tests.

Each bundle should contain:

- `events.parquet`: the complete normalized event set, including timing gaps and stable event IDs.
- `event_evidence.parquet`: normalized structured detector provenance and source-row references. The batch pipeline first writes `anomaly_event_evidence.parquet` beside `anomaly_events.parquet`; preparation combines this with timing-gap evidence into the bundle-level sidecar. Include the batch sidecar in cache-completeness checks and represent unavailable provenance explicitly for unsupported event types.
- `incidents.json`: versioned incident records and an evidence catalog. Member event IDs are complete; larger source-sample selections are identified by exact predicates with counts and a digest rather than copying every sample into JSON.

The artifact contract must cover:

| Field group | Required content |
| --- | --- |
| Identity | Schema version, dataset ID, analysis ID, source SHA-256, detector/recipe signature, grouping version, explanation catalog signature. |
| Incident | Stable incident ID, family, full topic names, recorded-time bounds, complete member-event IDs/count, and recorded grouping decisions. |
| Observation | Rule/template ID, rendered text, typed parameters with units, evidence references, and exact scope. |
| Possibilities | Reviewed possible explanations, any supporting or opposing evidence, and explicitly untested possibilities. No probabilities or unsupported ranking. |
| Limits | Missing inputs, extraction/sampling limits, clock/frame ambiguity, and what cannot be concluded. |
| Next checks | Reviewed action text, why it helps, required inputs, and whether those inputs are available in this bundle. |
| Evidence catalog | Artifact kind, event/sample/topic/field identifiers, exact interval, aggregation or selection rule, count, unit, clock basis, frame semantics, and availability. |
| UI hints | Relevant topic/field keys, incident focus time, and separate padded display bounds. These are hints, not additional measurements. |

Use integer nanoseconds for calculations and decimal strings in JSON; relative seconds are display coordinates. Preserve message sequence and duplicates. Event IDs derive from canonical source identity, typed event content, and stable source locators; they do not depend on display order, UUID analysis IDs, or prose. Preserve duplicate event multiplicity with deterministic occurrence identifiers. Incident IDs derive from sorted member IDs and the grouping version. Explanation versions can change wording without changing event identity.

Identical inputs must produce identical event/incident IDs and explanation content after excluding publication UUIDs, generation timestamps, and performance measurements. A schema/rule version change is explicit, not disguised as a repeat of the same recipe.

Represent measurement availability separately from interpretation: `available`, `partial`, `unavailable`, or `not_applicable`, with a reason. A zero count is different from a missing count; “no detected warnings” does not imply “healthy.” Unsupported events use `explanation_status: unsupported`, retain their evidence, and say that no supported explanation is available for that event type. Missing prerequisites for a known template use a distinct `insufficient_evidence` status.

## 2. Preserve the detector evidence needed for truthful explanations

Extend detector output through a sidecar rather than changing the meaning of existing anomaly columns. Wire sidecar publication and validation through `domain_analysis.py` and `pipeline.py`. Existing report and Parquet consumers should continue to work.

For the supported families, retain:

- Image warnings: failing sample count, analyzed sample count, finite-value coverage, min/max as appropriate, threshold/comparator, source sequences, and grouping policy. A low sharpness score is not automatically blur.
- Delivery gaps: the two boundary samples, recorded receive timestamps, interval length, configured rate/gap threshold and reference-topic role. Label the gap as a recorded interval, not measured packet loss. A gap overlapping a requested window must remain visible even when its boundary samples are outside that window.
- Motion warnings: command topic, chosen odometry topic, both thresholds, matching window/direction, selected source sample pairs, time offsets, speed definition, and available frame identifiers. Separate nearest-sample disagreement from the existing forward response-timeout check.

If multiple odometry topics exist, show the detector's selection policy and flag ambiguous association. Optional configured command-to-odometry relationships may gate explanatory context; they must not silently override the topic actually used by the detector. Changing that detector policy would be a separate reviewed change with its own regression evidence.

Any supporting delivery statement must be recomputed over the incident's stated interval from the complete message index, with boundary/coverage handling. An absence of gap rows in a truncated API response is not evidence of steady delivery. Prefer precise language such as “No recorded receive interval exceeded the configured threshold in the inspected coverage.” If coverage is insufficient, omit the claim and explain the missing boundary evidence.

## 3. Group events conservatively

Introduce a validated `configs/incident_explanations.yaml` catalog. It contains explanation definitions, grouping families, allowed relationships, and presentation context settings. Numeric detection thresholds remain in the existing analysis profiles. Rule predicates are implemented as named Python functions; YAML must not contain executable expressions.

First-release grouping policy:

1. Partition by source recording and known robot scope. A single bag does not establish that all topics belong to one robot; do not infer robot identity by stripping namespaces.
2. Preserve the detector's existing episodes. Do not merge nearby warnings again merely because they are close in time.
3. Merge compatible image-content warnings only on the same full topic when they overlap the seed event. Sort seeds deterministically by start, end, type, topic, and event ID. Treat equal-time point events explicitly as overlapping.
4. Require every added event to overlap the original seed, not just the expanding group bounds. Set a versioned maximum combined span of 10 seconds for merging multiple events; retain a longer original event intact as its own incident. This is an initial presentation policy to validate, not a physical-fault threshold.
5. Keep reference gaps, sensor gaps, and motion disagreements as separate incident families. Multiple topics can appear as supporting context, but temporal proximity alone never merges them into a shared failure.
6. Link explicitly configured counterparts, such as a stereo camera or a known command/odometry pair, as related context. Record the relationship and temporal rule. Do not assume a relationship from similar names.
7. Record why every merge or context link was allowed. Keep unsupported events as individual inspectable incidents.

No causal chain is generated from overlap. A continuous broad warning cannot join otherwise separate short episodes through repeated transitive merges. Raw events and their complete counts remain available underneath every incident.

Default ordering is chronological with stable ID tie-breaks. Preserve detector severity as a separate field; do not introduce an unvalidated “importance” or “confidence” score.

## 4. Author three explanation families and a fallback

Each catalog entry defines applicability, required evidence, observations, possible explanations, limitations, next checks, and relevant plot fields. Render text in Python from validated typed parameters; the frontend does not repeat the inference rules.

| Family | Supported statement | Limits and next checks |
| --- | --- | --- |
| Image content | Measured intensity/sharpness crossed recorded thresholds. Add delivery context only when independently checked. | Lighting, exposure, scene texture, motion, or obstruction may explain features; no camera malfunction or localization impact is established. Inspect source images, another camera, and exposure information where available. |
| Recorded/reference gap | A named stream has a measured receive-time gap exceeding its configured threshold. Reference topics are labeled as evaluation coverage. | Recorded timestamps do not establish acquisition order, network loss, or hardware synchronization. Inspect publisher/acquisition records; check whether the evaluation can use the affected reference interval. |
| Motion disagreement | A stated number of command samples met the commanded-speed condition while their matched odometry samples met the stationary-speed condition. | Show nearest-match offsets, frame limitations, and association ambiguity. Suggest inspecting angular motion, subsequent response, and controller feedback. Do not claim slip, stalled hardware, or localization loss. |
| Fallback | The named detector produced a warning with its available interval/value/threshold. | State that the engine has no supported explanation for this event type; link the original evidence without inventing hypotheses. |

Next checks adapt to availability: “Inspect angular velocity” can select a present series, while “Record controller feedback on a future run” is used when that data is absent. Never offer an evidence link to nonexistent data. Showing a nearby preview must display its actual timestamp and whether it is inside the incident; proximity is not proof that the preview supports a particular claim.

For this release, baseline comparison remains a manual interval inspection. Existing reviewed cases can suggest a nominal interval, but generated text cannot call it healthy or quote a comparison that the engine has not calculated. This keeps the first release focused on explainable incidents; a future comparison feature needs its own selection and comparability contract.

## 5. Integrate preparation and publication

Update `build_bundle()` to normalize events, generate provenance/incident artifacts, validate every reference and count, and only then publish metadata and `latest.json`. Failed preparation must leave the prior pointer and all prior bundles intact. A bundle with available observations but limited explanatory evidence is valid if those limits are explicit; corrupt identities or dangling evidence references are publication failures.

Include the effective explanation catalog and grouping configuration in `recipe_signature()`. Python files were already included; the implementation now also includes the validated YAML values, so semantic rule changes invalidate prepared evidence. Record artifact hashes in metadata and validate them before serving cached explanations, with file-stat-aware caching matching existing source-digest behavior.

Update `scripts/prepare_investigations.py` to report incident counts, supported/fallback counts, limited-evidence counts, and preparation failures. Keep annotation publication separate and clearly labeled; a missing reviewed annotation must not masquerade as an explanation-engine failure. If optional annotation attachment fails after core publication, report that separately from the successful evidence preparation. All artifacts required for generated explanations must be validated before the core pointer advances.

Expect existing prepared bundles to become stale when the recipe changes, as they already do after analysis-code changes. Regenerate into new UUID directories. Do not rewrite previous bundles or manufacture explanations from truncated legacy payloads. Older artifacts should produce an explicit preparation-required state rather than an exception exposed as a server error.

## 6. Add read-only API access

Extend the recording router with:

- `GET /api/investigations/{dataset_id}/incidents?analysis_id=...&offset=0&limit=50`: chronological summaries, total count, returned count, and pagination information. Enforce a maximum page size of 100. Optional start/end filters match overlapping incidents and keep original bounds; they do not regroup events.
- `GET /api/investigations/{dataset_id}/incidents/{incident_id}?analysis_id=...&member_offset=0&member_limit=50`: exact structured explanation, its bounded reference catalog, and a page of member events with full counts; maximum member page size 100. Keep complete membership in the saved artifact, not in every response. Large evidence selections use counted predicates/digests and bounded examples; no hidden “first 200” membership decisions.

Reuse the bundle loader and require exact current analysis identity on both routes. Return 404 for unknown datasets/incidents, 409 for changed or stale evidence, and validation errors for malformed bounds/pagination. Resolve incident IDs inside the validated bundle; do not accept filesystem paths from clients.

Keep metadata additions small: incident totals, explanation version, and availability. Preserve existing `events`, `cases`, and interval endpoints for current clients. Add allowlisted topic/field selection to interval evidence retrieval when needed so a requested supporting series cannot disappear behind the existing first-60-series limit. Counts and truncation flags must describe the selected scope accurately.

Read-only requests do not parse raw bags, run detectors, or write artifacts. The later **Rebuild evidence** flow explicitly starts a background worker through POST; its single-process lifecycle and retry behavior are documented in the usage guide. Cache incident artifacts by complete bundle/version identity and digest; validate before returning cached content.

## 7. Connect explanations to the workbench

Add `RecordingIncidentList.jsx` and `RecordingIncidentExplanation.jsx`, with focused tests, and integrate them into `RecordingInvestigation.jsx` and `RecordingInvestigation.css`.

The main flow is:

1. Select a prepared recording and see its incident count and chronological list.
2. Select an incident to open its explanation and set the shared plots to its relevant signals and padded display interval.
3. Read “What was observed,” “Supporting evidence,” “Possible explanations,” “What remains uncertain,” and “Next checks.” Display the grouping reason near the member-event list.
4. Select an evidence reference to focus a plot, source sample, or original event with the actual topic, unit, timestamp, and frame semantics visible.
5. Expand provenance for source, analysis, and rule versions.

Keep reviewed cases in a separately labeled control. Generated incidents must work when `recording_cases.yaml` has no entry for the recording. Selecting a reviewed case or manually choosing an interval clears the selected generated incident and its stale explanation. Moving the cursor within an incident updates inspection only; it does not regenerate or change the incident's conclusions.

Abort obsolete requests when the dataset or analysis changes, and clear old details while loading. Distinguish “no warnings detected,” “no supported explanation,” “insufficient evidence,” “not prepared,” and “stale evidence.” Preserve keyboard access, full topic names, the existing visual language, and narrow-screen usability.

## Delivery sequence and acceptance gates

| Step | Changes | Completion evidence |
| --- | --- | --- |
| 1. Contracts and provenance | New schema/modules/catalog; structured event provenance in detector/pipeline output. | Synthetic fixtures establish exact values, units, sample references, and detector parity. All new artifacts have validated identities. |
| 2. Grouping and templates | Complete-event normalization, stable IDs, conservative grouping, three supported families and fallback. | Deterministic grouping under shuffled inputs; every generated claim traces to its evidence; missing inputs suppress unsupported wording. |
| 3. Preparation and API | Atomic incident publication, recipe/digest checks, summaries/detail endpoints, bounded evidence lookup. | Old bundles are preserved; stale/tampered identities are rejected; full counts survive pagination and display limits. |
| 4. Workbench integration | Incident list/panel, linked plots/previews, reviewed-case separation and state handling. | User can select an incident, inspect evidence and follow an available next check without replay; dataset/interval changes clear old conclusions. |
| 5. Recorded-data review and docs | Reprepare available comparison recordings; inspect results and update usage/architecture documentation. | Review the three existing cases plus negative controls and unsupported cases, save an evidence summary, and pass relevant repository checks. |

The first useful vertical slice is **one camera-content incident generated from source evidence, served through the API and inspected in the UI**. It must include delivery-context gating, uncertainty, and evidence navigation. Then expand to the other families using the same contract before calling the release complete.

## Validation plan

Add `tests/test_incident_explanations.py`, `tests/test_incident_grouping.py`, frontend tests beside the new components, and a small offline browser flow. Extend `tests/test_domain_analysis.py`, `tests/test_domain_pipeline.py`, `tests/test_investigations.py`, `tests/demo/test_recording_investigation.py`, and `RecordingInvestigation.test.jsx` where their existing contracts change.

Required correctness checks:

- Same inputs and rule versions yield the same incident IDs, membership, typed values, and explanation content after publication metadata is removed.
- Existing detector event types, intervals, thresholds and counts remain unchanged when provenance is added.
- Overlapping compatible image warnings merge; unrelated topics, reference gaps, robot scopes, and transitive chains do not. Point events, long events, duplicate timestamps, and record-boundary gaps are explicit cases.
- More than 200 events and more than 60 available series do not alter analysis membership or make required evidence inaccessible. API display bounds preserve complete counts and pagination.
- Counts are calculated from the full applicable evidence, not from previews, buckets, event prose, or truncated lists. No evidence link points outside its source/analysis identity.
- Missing topics, unavailable fields, extraction errors, ambiguous odometry association, unknown frames, and insufficient boundary samples produce explicit limits rather than normal/zero values.
- Unknown event types have a factual fallback. Hypotheses never appear as measured causes. A nearest-sample match is never described as a measured forward response latency.
- Catalog/schema changes invalidate stale artifacts. Partial publication, tampered artifacts, unknown IDs, and stale requests fail predictably without damaging old evidence.
- UI selection, pagination, evidence navigation, unavailable states, manual interval changes, rapid recording switches, and keyboard operation behave correctly.

Use the reviewed TUM VI image/reference cases and LILocBench motion case as semantic acceptance examples, not physical-fault ground truth. Recompute their numeric assertions from the new prepared evidence. For recordings without reviewed cases, assess whether supported events receive valid explanations; a recording with no events is still a useful empty-state check. Include small synthetic fixtures in CI so validation does not require public dataset downloads.

During implementation, run focused tests after each step, then `make lint`, `make test`, `npm --prefix demo/web test`, and `npm --prefix demo/web run build`. Validate package build/cache completeness if batch artifacts change. Run the offline API/browser path and existing streaming UI regression tests; broader streaming/Compose checks remain the repository CI gate. Do not claim CI, physical-robot validation, or reduced investigation time from local unit tests.

Document the delivered schema, rule coverage, preparation command, example explanations, and limitations in `docs/recording-investigations.md` and `docs/architecture.md`; update README feature wording only after implementation and verification. A later usability comparison can measure time to a supported conclusion, unnecessary investigation steps, and whether users identify a useful next check.

## Definition of done

A user can open a prepared recording, choose a generated incident without selecting a curated case, inspect its measurements and source references, understand at least one explicit limitation, and take an appropriate next check. Explanations remain usable offline, reproducible, conservative about cause, and honest about missing evidence. Every original event remains inspectable, and the existing replay and localization workflows continue to work.
