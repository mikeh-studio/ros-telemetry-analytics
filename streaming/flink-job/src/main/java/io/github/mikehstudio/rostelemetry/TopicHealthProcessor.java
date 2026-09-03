package io.github.mikehstudio.rostelemetry;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.Serializable;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.apache.flink.api.common.functions.OpenContext;
import org.apache.flink.api.common.state.ListState;
import org.apache.flink.api.common.state.ListStateDescriptor;
import org.apache.flink.api.common.state.MapState;
import org.apache.flink.api.common.state.MapStateDescriptor;
import org.apache.flink.api.common.state.StateTtlConfig;
import org.apache.flink.api.common.state.ValueState;
import org.apache.flink.api.common.state.ValueStateDescriptor;
import org.apache.flink.metrics.Counter;
import org.apache.flink.streaming.api.TimerService;
import org.apache.flink.streaming.api.functions.KeyedProcessFunction;
import org.apache.flink.util.Collector;
import org.apache.flink.util.OutputTag;

final class TopicHealthProcessor extends KeyedProcessFunction<String, JsonNode, String> {
    static final OutputTag<String> ANOMALIES = new OutputTag<>("anomalies") {};
    static final OutputTag<String> LATE_EVENTS = new OutputTag<>("late-events") {};

    static final long WINDOW_MS = StreamingDefaults.WINDOW_MS;
    static final long SLIDE_MS = StreamingDefaults.SLIDE_MS;
    static final long RECOVERY_GATE_MS = StreamingDefaults.RECOVERY_GATE_MS;
    static final long ALLOWED_LATENESS_MS = StreamingDefaults.ALLOWED_LATENESS_MS;
    static final double MINIMUM_RATE_RATIO = StreamingDefaults.MINIMUM_RATE_RATIO;
    static final double MAXIMUM_RATE_RATIO = StreamingDefaults.MAXIMUM_RATE_RATIO;
    static final double GAP_MULTIPLIER = StreamingDefaults.GAP_THRESHOLD_MULTIPLIER;

    private transient ValueState<Registration> registration;
    private transient ValueState<String> lifecycle;
    private transient ValueState<Long> maxStreamTimestamp;
    private transient ValueState<Long> maxSourceTimestamp;
    private transient ValueState<Long> gapTimer;
    private transient ValueState<Long> startupTimer;
    private transient ValueState<Long> nextWindowTimer;
    private transient ValueState<Long> recoveryTimer;
    private transient ValueState<Long> summaryTimer;
    private transient ValueState<Long> missionEndStream;
    private transient ValueState<RecoveryGate> recoveryGate;
    private transient ValueState<Integer> badRateWindows;
    private transient ValueState<Integer> healthyRateWindows;
    private transient ValueState<Long> structuralRecoveryStream;
    private transient ValueState<Long> acceptedLateCount;
    private transient ValueState<Long> duplicateCount;
    private transient ValueState<Long> tooLateCount;
    private transient ListState<EventPoint> acceptedEvents;
    private transient MapState<String, Boolean> seenEventIds;
    private transient MapState<String, ConditionState> conditions;
    private transient MapState<Long, Integer> windowRevisions;
    private transient Counter processedEventsMetric;
    private transient Counter acceptedLateEventsMetric;
    private transient Counter duplicateEventsMetric;
    private transient Counter tooLateEventsMetric;

    @Override
    public void open(OpenContext openContext) {
        StateTtlConfig ttl = StreamingDefaults.stateTtl();
        registration = state("registration-v2", Registration.class, ttl);
        lifecycle = state("lifecycle-v2", String.class, ttl);
        maxStreamTimestamp = state("max-stream-timestamp-v2", Long.class, ttl);
        maxSourceTimestamp = state("max-source-timestamp-v2", Long.class, ttl);
        gapTimer = state("gap-timer-v2", Long.class, ttl);
        startupTimer = state("startup-timer-v2", Long.class, ttl);
        nextWindowTimer = state("next-window-timer-v2", Long.class, ttl);
        recoveryTimer = state("recovery-timer-v2", Long.class, ttl);
        summaryTimer = state("summary-timer-v2", Long.class, ttl);
        missionEndStream = state("mission-end-stream-v2", Long.class, ttl);
        recoveryGate = state("recovery-gate-v2", RecoveryGate.class, ttl);
        badRateWindows = state("bad-rate-windows-v2", Integer.class, ttl);
        healthyRateWindows = state("healthy-rate-windows-v2", Integer.class, ttl);
        structuralRecoveryStream = state("structural-recovery-stream-v2", Long.class, ttl);
        acceptedLateCount = state("accepted-late-count-v2", Long.class, ttl);
        duplicateCount = state("duplicate-count-v2", Long.class, ttl);
        tooLateCount = state("too-late-count-v2", Long.class, ttl);
        ListStateDescriptor<EventPoint> acceptedDescriptor =
                new ListStateDescriptor<>("accepted-events-v2", EventPoint.class);
        acceptedDescriptor.enableTimeToLive(ttl);
        acceptedEvents = getRuntimeContext().getListState(acceptedDescriptor);
        MapStateDescriptor<String, Boolean> dedupeDescriptor =
                new MapStateDescriptor<>("seen-event-ids-v2", String.class, Boolean.class);
        dedupeDescriptor.enableTimeToLive(ttl);
        seenEventIds = getRuntimeContext().getMapState(dedupeDescriptor);
        MapStateDescriptor<String, ConditionState> conditionDescriptor =
                new MapStateDescriptor<>("conditions-v2", String.class, ConditionState.class);
        conditionDescriptor.enableTimeToLive(ttl);
        conditions = getRuntimeContext().getMapState(conditionDescriptor);
        MapStateDescriptor<Long, Integer> revisionDescriptor =
                new MapStateDescriptor<>("window-revisions-v2", Long.class, Integer.class);
        revisionDescriptor.enableTimeToLive(ttl);
        windowRevisions = getRuntimeContext().getMapState(revisionDescriptor);
        var metrics = getRuntimeContext().getMetricGroup().addGroup("robot_telemetry");
        processedEventsMetric = metrics.counter("events_processed");
        acceptedLateEventsMetric = metrics.counter("accepted_late_events");
        duplicateEventsMetric = metrics.counter("duplicate_events");
        tooLateEventsMetric = metrics.counter("too_late_events");
    }

    private <T> ValueState<T> state(String name, Class<T> type, StateTtlConfig ttl) {
        ValueStateDescriptor<T> descriptor = new ValueStateDescriptor<>(name, type);
        descriptor.enableTimeToLive(ttl);
        return getRuntimeContext().getState(descriptor);
    }

    @Override
    public void processElement(JsonNode envelope, Context context, Collector<String> output)
            throws Exception {
        String type = envelope.path("envelope_type").asText();
        long streamTimestamp = envelope.path("stream_timestamp_ms").asLong();
        switch (type) {
            case "topic_registered" -> register(envelope, context);
            case "telemetry" -> processTelemetry(envelope, streamTimestamp, context, output);
            case "run_paused" -> pause(context);
            case "run_resumed" -> resume(context);
            case "run_aborted", "run_failed" -> abort(context);
            case "run_ended" -> endRun(streamTimestamp, context);
            case "watermark_flush" -> {
                // The assigned timestamp advances the source watermark. Finalization is timer-driven.
            }
            default -> {
                // Robot-scoped lifecycle records never enter this topic-keyed branch.
            }
        }
    }

    private void register(JsonNode envelope, Context context) throws Exception {
        JsonNode body = envelope.path("body");
        long streamStart = envelope.path("stream_timestamp_ms").asLong();
        Registration value = new Registration();
        value.runId = envelope.path("run_id").asText();
        value.robotId = envelope.path("robot_id").asText();
        value.topic = envelope.path("topic").asText();
        value.sourceStartNs = envelope.path("event_timestamp_ns").asLong();
        value.streamStartMs = streamStart;
        value.expectedRateHz = body.path("expected_rate_hz").asDouble();
        value.rateMonitoringEnabled = body.path("rate_monitoring_enabled").asBoolean(true);
        value.expectedTopicCount = body.path("expected_topic_count")
                .asInt(StreamingDefaults.EXPECTED_TOPIC_COUNT);
        value.datasetId = body.path("dataset_id").asText("warehouse_run_17");
        value.datasetName = body.path("dataset_name").asText("Warehouse Run 17");
        value.sourceFormat = body.path("source_format").asText("rosbag2_mcap");
        value.missionDurationMs = body.path("mission_duration_ms").asLong(90_000L);
        value.startupGraceMs = body.path("startup_grace_ms").asLong();
        value.dropoutThresholdMs = body.path("dropout_threshold_ms").asLong();
        registration.update(value);
        lifecycle.update("RUNNING");
        if (value.rateMonitoringEnabled) {
            long startup = streamStart + value.startupGraceMs;
            startupTimer.update(startup);
            context.timerService().registerEventTimeTimer(startup);
        }
        long firstWindow = streamStart + WINDOW_MS;
        nextWindowTimer.update(firstWindow);
        context.timerService().registerEventTimeTimer(firstWindow);
    }

    private void processTelemetry(
            JsonNode envelope,
            long streamTimestamp,
            Context context,
            Collector<String> output)
            throws Exception {
        processedEventsMetric.inc();
        Registration registered = registration.value();
        if (registered == null) {
            context.output(LATE_EVENTS, rejected(envelope, "unregistered_topic", Long.MIN_VALUE));
            return;
        }
        JsonNode body = envelope.path("body");
        String eventId = body.path("event_id").asText();
        long watermark = context.timerService().currentWatermark();
        TelemetryDisposition disposition = classifyTelemetry(
                seenEventIds.contains(eventId), watermark, streamTimestamp,
                "RUNNING".equals(lifecycle.value()));
        if (disposition == TelemetryDisposition.DUPLICATE) {
            increment(duplicateCount);
            duplicateEventsMetric.inc();
            context.output(LATE_EVENTS, rejected(envelope, "duplicate", watermark));
            return;
        }
        if (disposition == TelemetryDisposition.TOO_LATE) {
            increment(tooLateCount);
            tooLateEventsMetric.inc();
            seenEventIds.put(eventId, true);
            context.output(LATE_EVENTS, rejected(envelope, "beyond_allowed_lateness", watermark));
            return;
        }
        if (disposition == TelemetryDisposition.NOT_RUNNING) {
            context.output(LATE_EVENTS, rejected(envelope, "run_not_running", watermark));
            return;
        }

        seenEventIds.put(eventId, true);
        long sourceTimestamp = body.path("event_timestamp_ns").asLong();
        boolean acceptedLate = disposition == TelemetryDisposition.ACCEPTED_LATE;
        acceptedEvents.add(new EventPoint(streamTimestamp, sourceTimestamp, eventId, acceptedLate));
        if (acceptedLate) {
            increment(acceptedLateCount);
            acceptedLateEventsMetric.inc();
            reviseClosedWindows(streamTimestamp, watermark, context.getCurrentKey(), output);
            return;
        }

        Long currentMax = maxStreamTimestamp.value();
        if (currentMax == null || streamTimestamp > currentMax) {
            maxStreamTimestamp.update(streamTimestamp);
            Long currentSourceMax = maxSourceTimestamp.value();
            if (currentSourceMax == null || sourceTimestamp > currentSourceMax) {
                maxSourceTimestamp.update(sourceTimestamp);
            }
            if (registered.rateMonitoringEnabled) {
                replaceGapTimer(streamTimestamp + registered.dropoutThresholdMs, context);
            }
        }
        advanceStructuralRecovery(streamTimestamp, registered, context);
    }

    static TelemetryDisposition classifyTelemetry(
            boolean seen, long watermark, long timestamp, boolean running) {
        if (seen) return TelemetryDisposition.DUPLICATE;
        if (watermark != Long.MIN_VALUE && timestamp < watermark - ALLOWED_LATENESS_MS) {
            return TelemetryDisposition.TOO_LATE;
        }
        if (!running) return TelemetryDisposition.NOT_RUNNING;
        if (watermark != Long.MIN_VALUE && timestamp < watermark) {
            return TelemetryDisposition.ACCEPTED_LATE;
        }
        return TelemetryDisposition.ACCEPTED_ON_TIME;
    }

    private void replaceGapTimer(long target, Context context) throws Exception {
        Long previous = gapTimer.value();
        if (previous != null && previous != target && !isSharedTimer(previous)) {
            context.timerService().deleteEventTimeTimer(previous);
        }
        gapTimer.update(target);
        context.timerService().registerEventTimeTimer(target);
    }

    private void advanceStructuralRecovery(
            long timestamp, Registration registered, Context context) throws Exception {
        if (!conditions.contains("NEVER_SEEN") && !conditions.contains("GAP")) return;
        RecoveryGate gate = recoveryGate.value();
        if (gate == null) {
            gate = new RecoveryGate();
            gate.startMs = timestamp;
            gate.lastMs = timestamp;
            gate.eventCount = 1;
            gate.gapFree = true;
            recoveryGate.update(gate);
            long target = timestamp + RECOVERY_GATE_MS;
            recoveryTimer.update(target);
            context.timerService().registerEventTimeTimer(target);
            return;
        }
        if (timestamp >= gate.startMs + RECOVERY_GATE_MS) return;
        if (timestamp > gate.lastMs) {
            double gapThresholdMs = GAP_MULTIPLIER / registered.expectedRateHz * 1_000.0;
            gate.gapFree = gate.gapFree && timestamp - gate.lastMs <= gapThresholdMs;
            gate.lastMs = timestamp;
            gate.eventCount += 1;
            recoveryGate.update(gate);
        }
    }

    private void reviseClosedWindows(
            long eventTimestamp, long watermark, String key, Collector<String> output)
            throws Exception {
        Registration registered = registration.value();
        long firstEnd = registered.streamStartMs + WINDOW_MS;
        long relative = eventTimestamp - registered.streamStartMs;
        long end = registered.streamStartMs
                + Math.floorDiv(relative, SLIDE_MS) * SLIDE_MS
                + SLIDE_MS;
        end = Math.max(end, firstEnd);
        for (; end <= eventTimestamp + WINDOW_MS && end <= watermark; end += SLIDE_MS) {
            Long missionEnd = missionEndStream.value();
            if (missionEnd != null && end > missionEnd) break;
            emitWindow(key, end, nextRevision(end), false, null, output);
        }
    }

    private void pause(Context context) throws Exception {
        lifecycle.update("PAUSED");
        cancelTimerRegistrations(context.timerService(), true, false);
    }

    private void resume(Context context) throws Exception {
        lifecycle.update("RUNNING");
        Registration registered = registration.value();
        if (registered == null) return;
        if (maxStreamTimestamp.value() == null && !conditions.contains("NEVER_SEEN")) {
            rearm(startupTimer.value(), context);
        }
        rearm(gapTimer.value(), context);
        rearm(nextWindowTimer.value(), context);
        rearm(recoveryTimer.value(), context);
    }

    private void abort(Context context) throws Exception {
        lifecycle.update("ABORTED");
        cancelTimerRegistrations(context.timerService(), true, true);
        clearState();
    }

    private void endRun(long timestamp, Context context) throws Exception {
        lifecycle.update("ENDED");
        cancelTimerRegistrations(context.timerService(), false, false);
        missionEndStream.update(timestamp);
        long summaryTarget = timestamp + ALLOWED_LATENESS_MS;
        summaryTimer.update(summaryTarget);
        context.timerService().registerEventTimeTimer(summaryTarget);
    }

    private void rearm(Long timer, Context context) {
        if (timer != null) context.timerService().registerEventTimeTimer(timer);
    }

    @Override
    public void onTimer(long timestamp, OnTimerContext context, Collector<String> output)
            throws Exception {
        Registration registered = registration.value();
        if (registered == null) return;
        Long startup = startupTimer.value();
        if (startup != null && timestamp == startup && maxStreamTimestamp.value() == null
                && "RUNNING".equals(lifecycle.value())) {
            openCondition(
                    "NEVER_SEEN",
                    registered.streamStartMs + registered.startupGraceMs,
                    timestamp,
                    evidence("messages_seen", 0),
                    context);
        }
        Long gap = gapTimer.value();
        if (gap != null && timestamp == gap && "RUNNING".equals(lifecycle.value())) {
            Long maximum = maxStreamTimestamp.value();
            if (maximum != null && timestamp >= maximum + registered.dropoutThresholdMs) {
                ObjectNode evidence = evidence("silence_ms", timestamp - maximum);
                evidence.put("watermark_ms", context.timerService().currentWatermark());
                openCondition("GAP", timestamp, timestamp, evidence, context);
            }
        }
        Long recovery = recoveryTimer.value();
        if (recovery != null && timestamp == recovery && "RUNNING".equals(lifecycle.value())) {
            evaluateStructuralRecovery(timestamp, registered, context);
        }
        Long window = nextWindowTimer.value();
        if (window != null
                && timestamp == window
                && ("RUNNING".equals(lifecycle.value()) || "ENDED".equals(lifecycle.value()))) {
            Long missionEnd = missionEndStream.value();
            if (missionEnd == null || timestamp <= missionEnd) {
                emitWindow(context.getCurrentKey(), timestamp, nextRevision(timestamp), false, context, output);
                long next = timestamp + SLIDE_MS;
                if (missionEnd == null || next <= missionEnd) {
                    nextWindowTimer.update(next);
                    context.timerService().registerEventTimeTimer(next);
                }
            }
        }
        Long summary = summaryTimer.value();
        if (summary != null && timestamp == summary && "ENDED".equals(lifecycle.value())) {
            emitTrailingPartialWindows(context.getCurrentKey(), output);
            emitMissionSummary(context.getCurrentKey(), output);
            clearState();
        }
    }

    private void evaluateStructuralRecovery(
            long timestamp, Registration registered, OnTimerContext context) throws Exception {
        RecoveryGate gate = recoveryGate.value();
        recoveryGate.clear();
        recoveryTimer.clear();
        if (gate == null) return;
        int required =
                Math.max(3, (int) Math.ceil(registered.expectedRateHz * MINIMUM_RATE_RATIO));
        if (gate.eventCount < required || !gate.gapFree) return;
        ObjectNode evidence = evidence("recovery_event_count", gate.eventCount);
        evidence.put("recovery_gate_ms", RECOVERY_GATE_MS);
        recoverCondition("NEVER_SEEN", timestamp, evidence, context);
        recoverCondition("GAP", timestamp, evidence, context);
        structuralRecoveryStream.update(timestamp);
        badRateWindows.update(0);
        healthyRateWindows.update(0);
    }

    private void emitWindow(
            String key,
            long windowEnd,
            int revision,
            boolean partial,
            OnTimerContext timerContext,
            Collector<String> output)
            throws Exception {
        Registration registered = registration.value();
        long windowStart = windowEnd - WINDOW_MS;
        long actualEnd = partial ? missionEndStream.value() : windowEnd;
        List<EventPoint> points = eventsInRange(windowStart, actualEnd);
        double rollingRate = points.size() / (WINDOW_MS / 1_000.0);
        double ratio = rollingRate / registered.expectedRateHz;
        List<Long> sourceTimestamps = points.stream().map(point -> point.sourceTimestampNs).toList();
        HealthMath.Summary timing = HealthMath.summarize(
                sourceTimestamps,
                registered.expectedRateHz,
                GAP_MULTIPLIER,
                MINIMUM_RATE_RATIO,
                MAXIMUM_RATE_RATIO,
                1_000_000_000L);
        String suppression = structuralSuppression(windowEnd);
        ObjectNode payload = summaryPayload(timing);
        payload.put("mean_rate_hz", rollingRate);
        payload.put("rate_ratio", ratio);
        payload.put("window_status", partial ? "partial" : "complete");
        payload.put("accepted_late_count", countLate(points));
        payload.put("duplicate_count", longValue(duplicateCount));
        payload.put("too_late_count", longValue(tooLateCount));
        payload.put("rate_monitoring_enabled", registered.rateMonitoringEnabled);
        payload.put("expected_topic_count", registered.expectedTopicCount);
        payload.put("dataset_id", registered.datasetId);
        payload.put("dataset_name", registered.datasetName);
        payload.put("source_format", registered.sourceFormat);
        payload.put("mission_duration_ms", registered.missionDurationMs);
        boolean recoveryInProgress = recoveryInProgress();
        payload.put("recovery_in_progress", recoveryInProgress);
        payload.put("health_status", conditions.isEmpty()
                ? "healthy"
                : recoveryInProgress ? "recovering" : "degraded");
        var activeConditions = payload.putArray("active_conditions");
        for (String condition : conditions.keys()) activeConditions.add(condition);
        if (suppression == null) payload.putNull("health_transition_suppressed_by");
        else payload.put("health_transition_suppressed_by", suppression);
        output.collect(metric(
                "topic_window",
                key,
                windowStart,
                windowEnd,
                revision,
                actualEnd,
                payload));

        if (partial
                || revision != 0
                || timerContext == null
                || !registered.rateMonitoringEnabled
                || !"RUNNING".equals(lifecycle.value())) return;
        Long recoveredAt = structuralRecoveryStream.value();
        boolean eligibleAfterRecovery = recoveredAt == null || windowStart >= recoveredAt;
        if (suppression != null || !eligibleAfterRecovery) {
            badRateWindows.update(0);
            healthyRateWindows.update(0);
            return;
        }
        boolean bad = ratio < MINIMUM_RATE_RATIO || ratio > MAXIMUM_RATE_RATIO;
        if (bad) {
            int streak = intValue(badRateWindows) + 1;
            badRateWindows.update(streak);
            healthyRateWindows.update(0);
            if (streak >= 2) {
                ObjectNode evidence = evidence("rate_ratio", ratio);
                evidence.put("consecutive_bad_windows", streak);
                openCondition("RATE", windowStart, windowEnd, evidence, timerContext);
            }
        } else {
            badRateWindows.update(0);
            int streak = intValue(healthyRateWindows) + 1;
            healthyRateWindows.update(streak);
            if (streak >= 2) {
                ObjectNode evidence = evidence("rate_ratio", ratio);
                evidence.put("consecutive_healthy_windows", streak);
                recoverCondition("RATE", windowEnd, evidence, timerContext);
            }
        }
    }

    private boolean recoveryInProgress() throws Exception {
        if (recoveryGate.value() != null) return true;
        return conditions.contains("RATE") && intValue(healthyRateWindows) > 0;
    }

    private void emitTrailingPartialWindows(String key, Collector<String> output) throws Exception {
        Long missionEnd = missionEndStream.value();
        if (missionEnd == null) return;
        for (int slide = 1; slide < 10; slide++) {
            long start = missionEnd - WINDOW_MS + slide * SLIDE_MS;
            emitWindow(key, start + WINDOW_MS, 0, true, null, output);
        }
    }

    private void emitMissionSummary(String key, Collector<String> output) throws Exception {
        Registration registered = registration.value();
        List<Long> sourceTimestamps = new ArrayList<>();
        for (EventPoint point : acceptedEvents.get()) sourceTimestamps.add(point.sourceTimestampNs);
        HealthMath.Summary summary = HealthMath.summarize(
                sourceTimestamps,
                registered.expectedRateHz,
                GAP_MULTIPLIER,
                MINIMUM_RATE_RATIO,
                MAXIMUM_RATE_RATIO,
                1_000_000_000L);
        ObjectNode payload = summaryPayload(summary);
        payload.put("accepted_late_count", longValue(acceptedLateCount));
        payload.put("duplicate_count", longValue(duplicateCount));
        payload.put("too_late_count", longValue(tooLateCount));
        payload.put("rate_monitoring_enabled", registered.rateMonitoringEnabled);
        payload.put("expected_topic_count", registered.expectedTopicCount);
        payload.put("dataset_id", registered.datasetId);
        payload.put("dataset_name", registered.datasetName);
        payload.put("source_format", registered.sourceFormat);
        payload.put("mission_duration_ms", registered.missionDurationMs);
        Long end = missionEndStream.value();
        output.collect(metric("mission_summary", key, null, null, 0, end, payload));
    }

    private List<EventPoint> eventsInRange(long startInclusive, long endExclusive) throws Exception {
        List<EventPoint> result = new ArrayList<>();
        for (EventPoint point : acceptedEvents.get()) {
            if (point.streamTimestampMs >= startInclusive && point.streamTimestampMs < endExclusive) {
                result.add(point);
            }
        }
        return result;
    }

    private long countLate(List<EventPoint> points) {
        return points.stream().filter(point -> point.acceptedLate).count();
    }

    private String structuralSuppression(long windowEnd) throws Exception {
        if (conditions.contains("NEVER_SEEN")) return "NEVER_SEEN";
        if (conditions.contains("GAP")) return "GAP";
        Long pendingGap = gapTimer.value();
        if (pendingGap != null
                && maxStreamTimestamp.value() != null
                && pendingGap <= windowEnd + SLIDE_MS) return "GAP";
        return null;
    }

    private void openCondition(
            String name,
            long effectiveStart,
            long detected,
            ObjectNode evidence,
            OnTimerContext context)
            throws Exception {
        if (conditions.contains(name)) return;
        ConditionState state = new ConditionState();
        state.effectiveStartMs = effectiveStart;
        String[] keyParts = context.getCurrentKey().split("\\|", 3);
        state.anomalyId = JsonSupport.sha256(
                keyParts[0], keyParts[1], keyParts[2], name, effectiveStart);
        state.revision = 0;
        if (name.equals("GAP")) state.lastOnTimeSourceTimestampNs = maxSourceTimestamp.value();
        conditions.put(name, state);
        enrichEvidence(evidence, detected, state);
        emitAnomaly(name, "active", state, detected, evidence, context);
    }

    private void recoverCondition(
            String name, long detected, ObjectNode evidence, OnTimerContext context) throws Exception {
        ConditionState state = conditions.get(name);
        if (state == null) return;
        state.revision += 1;
        enrichEvidence(evidence, detected, state);
        emitAnomaly(name, "recovered", state, detected, evidence, context);
        conditions.remove(name);
    }

    private void enrichEvidence(ObjectNode evidence, long detected, ConditionState state)
            throws Exception {
        Registration registered = registration.value();
        if (registered != null) {
            evidence.put("expected_rate_hz", registered.expectedRateHz);
            if (!evidence.has("observed_rate_hz")) {
                int count = eventsInRange(detected - WINDOW_MS, detected).size();
                evidence.put("observed_rate_hz", count / (WINDOW_MS / 1_000.0));
            }
        }
        evidence.put("accepted_late_count", longValue(acceptedLateCount));
        if (registered != null && state.lastOnTimeSourceTimestampNs != null) {
            long detectedSourceTimestampNs = registered.sourceStartNs
                    + Math.max(0, detected - registered.streamStartMs) * 1_000_000L;
            evidence.put(
                    "incident_duration_ms",
                    Math.max(
                            0,
                            Math.floorDiv(
                                    detectedSourceTimestampNs
                                            - state.lastOnTimeSourceTimestampNs,
                                    1_000_000L)));
            evidence.put(
                    "last_on_time_source_timestamp_ns",
                    state.lastOnTimeSourceTimestampNs);
        } else {
            evidence.put("incident_duration_ms", Math.max(0, detected - state.effectiveStartMs));
        }
    }

    private void emitAnomaly(
            String condition,
            String status,
            ConditionState state,
            long detected,
            JsonNode evidence,
            OnTimerContext context) {
        String[] parts = context.getCurrentKey().split("\\|", 3);
        ObjectNode node = JsonSupport.object();
        node.put("schema_version", 1);
        node.put("anomaly_id", state.anomalyId);
        node.put("run_id", parts[0]);
        node.put("robot_id", parts[1]);
        node.put("topic", parts[2]);
        node.put("condition_type", condition);
        node.put("status", status);
        node.put("severity", condition.equals("NEVER_SEEN") ? "error" : "warn");
        node.put("revision", state.revision);
        node.put("effective_start_stream_ms", state.effectiveStartMs);
        node.put("detected_stream_ms", detected);
        if (status.equals("recovered")) node.put("recovered_stream_ms", detected);
        else node.putNull("recovered_stream_ms");
        node.set("evidence", evidence);
        context.output(ANOMALIES, JsonSupport.write(node));
    }

    private String metric(
            String metricType,
            String key,
            Long windowStart,
            Long windowEnd,
            int revision,
            long streamTimestamp,
            ObjectNode payload) {
        String[] parts = key.split("\\|", 3);
        ObjectNode node = JsonSupport.object();
        node.put("schema_version", 1);
        node.put(
                "metric_id",
                JsonSupport.sha256(
                        1,
                        parts[0],
                        parts[1],
                        parts[2],
                        windowStart,
                        windowEnd,
                        revision));
        node.put("metric_type", metricType);
        node.put("run_id", parts[0]);
        node.put("robot_id", parts[1]);
        node.put("topic", parts[2]);
        if (windowStart == null) node.putNull("window_start_ms");
        else node.put("window_start_ms", windowStart);
        if (windowEnd == null) node.putNull("window_end_ms");
        else node.put("window_end_ms", windowEnd);
        node.put("revision", revision);
        node.put("stream_timestamp_ms", streamTimestamp);
        node.set("payload", payload);
        return JsonSupport.write(node);
    }

    private static ObjectNode summaryPayload(HealthMath.Summary summary) {
        ObjectNode payload = JsonSupport.object();
        payload.put("message_count", summary.messageCount());
        putNullable(payload, "first_timestamp_ns", summary.firstTimestampMs());
        putNullable(payload, "last_timestamp_ns", summary.lastTimestampMs());
        putNullable(payload, "duration_s", summary.durationSeconds());
        putNullable(payload, "mean_rate_hz", summary.meanRateHz());
        payload.put("expected_rate_hz", summary.expectedRateHz());
        putNullable(payload, "rate_ratio", summary.rateRatio());
        putNullable(payload, "max_inter_message_gap_s", summary.maxGapSeconds());
        putNullable(payload, "p95_inter_message_gap_s", summary.p95GapSeconds());
        payload.put("gap_threshold_s", summary.gapThresholdSeconds());
        payload.put("gap_event_count", summary.gapEventCount());
        payload.put("estimated_dropped_messages", summary.estimatedDroppedMessages());
        payload.put("status", summary.status());
        return payload;
    }

    private static void putNullable(ObjectNode node, String name, Number value) {
        if (value == null) node.putNull(name);
        else if (value instanceof Long) node.put(name, value.longValue());
        else node.put(name, value.doubleValue());
    }

    private String rejected(JsonNode envelope, String reason, long watermark) {
        ObjectNode node = JsonSupport.object();
        node.put("schema_version", 1);
        node.put("reason", reason);
        node.put("event_id", envelope.path("body").path("event_id").asText("unknown"));
        node.put("run_id", envelope.path("run_id").asText());
        node.put("robot_id", envelope.path("robot_id").asText());
        node.put("topic", envelope.path("topic").asText());
        node.put("watermark_ms", watermark);
        node.set("envelope", envelope);
        return JsonSupport.write(node);
    }

    private static ObjectNode evidence(String name, Number value) {
        ObjectNode evidence = JsonSupport.object();
        if (value == null) evidence.putNull(name);
        else evidence.put(name, value.doubleValue());
        return evidence;
    }

    private int nextRevision(long windowEnd) throws Exception {
        Integer current = windowRevisions.get(windowEnd);
        int next = current == null ? 0 : current + 1;
        windowRevisions.put(windowEnd, next);
        return next;
    }

    private void increment(ValueState<Long> state) throws Exception {
        state.update(longValue(state) + 1);
    }

    private static long longValue(ValueState<Long> state) throws Exception {
        Long current = state.value();
        return current == null ? 0 : current;
    }

    private static int intValue(ValueState<Integer> state) throws Exception {
        Integer current = state.value();
        return current == null ? 0 : current;
    }

    private void cancelTimerRegistrations(
            TimerService timers, boolean includeWindows, boolean includeSummary) throws Exception {
        Set<Long> cancelled = new HashSet<>();
        addTimer(cancelled, startupTimer.value());
        addTimer(cancelled, gapTimer.value());
        addTimer(cancelled, recoveryTimer.value());
        if (includeWindows) addTimer(cancelled, nextWindowTimer.value());
        if (includeSummary) addTimer(cancelled, summaryTimer.value());

        Set<Long> retained = new HashSet<>();
        if (!includeWindows) addTimer(retained, nextWindowTimer.value());
        if (!includeSummary) addTimer(retained, summaryTimer.value());
        cancelled.removeAll(retained);
        for (Long timestamp : cancelled) deleteTimer(timers, timestamp);
    }

    private boolean isSharedTimer(Long timestamp) throws Exception {
        return timestamp.equals(startupTimer.value())
                || timestamp.equals(nextWindowTimer.value())
                || timestamp.equals(recoveryTimer.value())
                || timestamp.equals(summaryTimer.value());
    }

    private static void addTimer(Set<Long> timestamps, Long timestamp) {
        if (timestamp != null) timestamps.add(timestamp);
    }

    private static void deleteTimer(TimerService timers, Long timestamp) {
        if (timestamp != null) timers.deleteEventTimeTimer(timestamp);
    }

    private void clearState() throws Exception {
        registration.clear();
        lifecycle.clear();
        maxStreamTimestamp.clear();
        maxSourceTimestamp.clear();
        gapTimer.clear();
        startupTimer.clear();
        nextWindowTimer.clear();
        recoveryTimer.clear();
        summaryTimer.clear();
        missionEndStream.clear();
        recoveryGate.clear();
        badRateWindows.clear();
        healthyRateWindows.clear();
        structuralRecoveryStream.clear();
        acceptedLateCount.clear();
        duplicateCount.clear();
        tooLateCount.clear();
        acceptedEvents.clear();
        seenEventIds.clear();
        conditions.clear();
        windowRevisions.clear();
    }

    public static final class Registration implements Serializable {
        public String runId;
        public String robotId;
        public String topic;
        public long sourceStartNs;
        public long streamStartMs;
        public double expectedRateHz;
        public boolean rateMonitoringEnabled;
        public int expectedTopicCount;
        public String datasetId;
        public String datasetName;
        public String sourceFormat;
        public long missionDurationMs;
        public long startupGraceMs;
        public long dropoutThresholdMs;

        public Registration() {}
    }

    public static final class EventPoint implements Serializable {
        public long streamTimestampMs;
        public long sourceTimestampNs;
        public String eventId;
        public boolean acceptedLate;

        public EventPoint() {}

        EventPoint(
                long streamTimestampMs,
                long sourceTimestampNs,
                String eventId,
                boolean acceptedLate) {
            this.streamTimestampMs = streamTimestampMs;
            this.sourceTimestampNs = sourceTimestampNs;
            this.eventId = eventId;
            this.acceptedLate = acceptedLate;
        }
    }

    public static final class RecoveryGate implements Serializable {
        public long startMs;
        public long lastMs;
        public int eventCount;
        public boolean gapFree;

        public RecoveryGate() {}
    }

    public static final class ConditionState implements Serializable {
        public String anomalyId;
        public long effectiveStartMs;
        public int revision;
        public Long lastOnTimeSourceTimestampNs;

        public ConditionState() {}
    }

    enum TelemetryDisposition {
        ACCEPTED_ON_TIME,
        ACCEPTED_LATE,
        DUPLICATE,
        TOO_LATE,
        NOT_RUNNING
    }
}
