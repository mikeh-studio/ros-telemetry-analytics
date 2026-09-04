package io.github.mikehstudio.rostelemetry;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.Serializable;
import org.apache.flink.api.common.functions.OpenContext;
import org.apache.flink.api.common.state.MapState;
import org.apache.flink.api.common.state.MapStateDescriptor;
import org.apache.flink.api.common.state.ValueState;
import org.apache.flink.api.common.state.ValueStateDescriptor;
import org.apache.flink.streaming.api.TimeDomain;
import org.apache.flink.streaming.api.functions.KeyedProcessFunction;
import org.apache.flink.util.Collector;
import org.apache.flink.util.OutputTag;

/** Processing-time watchdog for the whole robot, fed only by accepted on-time events. */
final class RobotLivenessProcessor extends KeyedProcessFunction<String, JsonNode, String> {
    static final OutputTag<String> ANOMALIES = new OutputTag<>("robot-liveness-anomalies") {};
    private static final long OFFLINE_AFTER_MS = StreamingDefaults.WHOLE_ROBOT_SILENCE_MS;

    private final long idleTimeoutMs;
    private transient RunStateRetention retention;
    private transient ValueState<String> lifecycle;
    private transient ValueState<Boolean> watchdogEnabled;
    private transient ValueState<Long> watchdogTimer;
    private transient ValueState<Long> latestStreamTimestamp;
    private transient ValueState<OfflineState> offline;
    private transient ValueState<Integer> recoveryEvents;
    private transient ValueState<Identity> identity;
    private transient MapState<String, Boolean> seenEventIds;

    RobotLivenessProcessor() {
        this(RunStateRetention.configuredIdleTimeoutMs());
    }

    RobotLivenessProcessor(long idleTimeoutMs) {
        this.idleTimeoutMs = idleTimeoutMs;
    }

    @Override
    public void open(OpenContext ignored) {
        retention = new RunStateRetention(getRuntimeContext(), idleTimeoutMs);
        lifecycle = state("robot-lifecycle-v2", String.class);
        watchdogEnabled = state("robot-watchdog-enabled-v2", Boolean.class);
        watchdogTimer = state("robot-watchdog-timer-v2", Long.class);
        latestStreamTimestamp = state("robot-latest-stream-v2", Long.class);
        offline = state("robot-offline-v2", OfflineState.class);
        recoveryEvents = state("robot-recovery-events-v2", Integer.class);
        identity = state("robot-identity-v2", Identity.class);
        MapStateDescriptor<String, Boolean> seen =
                new MapStateDescriptor<>("robot-seen-liveness-events-v3", String.class, Boolean.class);
        seenEventIds = getRuntimeContext().getMapState(seen);
    }

    private <T> ValueState<T> state(String name, Class<T> type) {
        ValueStateDescriptor<T> descriptor = new ValueStateDescriptor<>(name, type);
        return getRuntimeContext().getState(descriptor);
    }

    @Override
    public void processElement(JsonNode envelope, Context context, Collector<String> output)
            throws Exception {
        retention.touch(context.timerService());
        String type = envelope.path("envelope_type").asText();
        long streamTimestamp = envelope.path("stream_timestamp_ms").asLong();
        switch (type) {
            case "run_started" -> {
                rememberIdentity(envelope);
                lifecycle.update("RUNNING");
                boolean enabled = envelope.path("body").path("replay_rate").asInt(1) == 1;
                watchdogEnabled.update(enabled);
                recoveryEvents.update(0);
                output.collect(metric(streamTimestamp, "healthy", "run_started"));
                if (enabled) replaceTimer(context);
            }
            case "run_paused" -> {
                lifecycle.update("PAUSED");
                cancelTimer(context);
            }
            case "run_resumed" -> {
                lifecycle.update("RUNNING");
                if (Boolean.TRUE.equals(watchdogEnabled.value())) replaceTimer(context);
            }
            case "run_aborted", "run_failed", "run_ended" -> {
                lifecycle.update(type.equals("run_ended") ? "ENDED" : type.toUpperCase());
                cancelTimer(context);
                retention.clear(context.timerService());
                clearState();
            }
            case "telemetry" -> {
                if (isAcceptedOnTime(envelope, context)) {
                    acceptedEvent(streamTimestamp, context, output);
                }
            }
            default -> {
                // Topic registrations and watermark flushes do not prove liveness.
            }
        }
    }

    private boolean isAcceptedOnTime(JsonNode envelope, Context context) throws Exception {
        if (!"RUNNING".equals(lifecycle.value())) return false;
        String eventId = envelope.path("body").path("event_id").asText();
        if (seenEventIds.contains(eventId)) return false;
        seenEventIds.put(eventId, true);
        long watermark = context.timerService().currentWatermark();
        return watermark == Long.MIN_VALUE
                || envelope.path("stream_timestamp_ms").asLong() >= watermark;
    }

    private void acceptedEvent(long streamTimestamp, Context context, Collector<String> output)
            throws Exception {
        if (!"RUNNING".equals(lifecycle.value())) return;
        Long latest = latestStreamTimestamp.value();
        if (latest == null || streamTimestamp > latest) latestStreamTimestamp.update(streamTimestamp);
        if (Boolean.TRUE.equals(watchdogEnabled.value())) replaceTimer(context);
        OfflineState active = offline.value();
        if (active == null) {
            recoveryEvents.update(0);
            return;
        }
        int consecutive = recoveryEvents.value() == null ? 1 : recoveryEvents.value() + 1;
        recoveryEvents.update(consecutive);
        output.collect(metric(streamTimestamp, "recovering", "accepted_event"));
        if (consecutive >= 3) {
            active.revision += 1;
            context.output(ANOMALIES, anomaly("recovered", streamTimestamp, active));
            offline.clear();
            recoveryEvents.update(0);
            output.collect(metric(streamTimestamp, "healthy", "three_accepted_events"));
        }
    }

    @Override
    public void onTimer(long timestamp, OnTimerContext context, Collector<String> output)
            throws Exception {
        if (context.timeDomain() == TimeDomain.PROCESSING_TIME && retention.expires(timestamp)) {
            Long watchdog = watchdogTimer.value();
            if (watchdog != null) context.timerService().deleteProcessingTimeTimer(watchdog);
            retention.clear(context.timerService());
            clearState();
            return;
        }
        if (context.timeDomain() != TimeDomain.PROCESSING_TIME
                || !"RUNNING".equals(lifecycle.value())
                || !Boolean.TRUE.equals(watchdogEnabled.value())
                || watchdogTimer.value() == null
                || watchdogTimer.value() != timestamp) return;
        if (offline.value() == null) {
            OfflineState state = new OfflineState();
            Long latest = latestStreamTimestamp.value();
            state.startMs = latest == null
                    ? identity.value().startStreamMs + OFFLINE_AFTER_MS
                    : latest + OFFLINE_AFTER_MS;
            String[] keyParts = context.getCurrentKey().split("\\|", 2);
            state.anomalyId = JsonSupport.sha256(
                    keyParts[0], keyParts[1], "__robot__", "ROBOT_OFFLINE", state.startMs);
            state.revision = 0;
            offline.update(state);
            context.output(ANOMALIES, anomaly("active", state.startMs, state));
            output.collect(metric(state.startMs, "offline", "processing_watchdog"));
        }
        watchdogTimer.clear();
    }

    private void replaceTimer(Context context) throws Exception {
        cancelTimer(context);
        long target = context.timerService().currentProcessingTime() + OFFLINE_AFTER_MS;
        watchdogTimer.update(target);
        context.timerService().registerProcessingTimeTimer(target);
    }

    private void cancelTimer(Context context) throws Exception {
        Long current = watchdogTimer.value();
        if (current != null) context.timerService().deleteProcessingTimeTimer(current);
        watchdogTimer.clear();
    }

    private void rememberIdentity(JsonNode envelope) throws Exception {
        if (identity.value() != null) return;
        Identity value = new Identity();
        value.runId = envelope.path("run_id").asText();
        value.robotId = envelope.path("robot_id").asText();
        value.startStreamMs = envelope.path("stream_timestamp_ms").asLong();
        identity.update(value);
    }

    private void clearState() {
        lifecycle.clear();
        watchdogEnabled.clear();
        watchdogTimer.clear();
        latestStreamTimestamp.clear();
        offline.clear();
        recoveryEvents.clear();
        identity.clear();
        seenEventIds.clear();
    }

    private String metric(long streamTimestamp, String status, String reason) throws Exception {
        Identity id = identity.value();
        ObjectNode node = JsonSupport.object();
        node.put("schema_version", 1);
        node.put("metric_id", JsonSupport.sha256(
                1, id.runId, id.robotId, "robot_health", streamTimestamp, status, 0));
        node.put("metric_type", "robot_health");
        node.put("run_id", id.runId);
        node.put("robot_id", id.robotId);
        node.putNull("topic");
        node.putNull("window_start_ms");
        node.put("window_end_ms", streamTimestamp);
        node.put("revision", 0);
        node.put("stream_timestamp_ms", streamTimestamp);
        ObjectNode payload = node.putObject("payload");
        payload.put("status", status);
        payload.put("reason", reason);
        payload.put("watchdog_enabled", Boolean.TRUE.equals(watchdogEnabled.value()));
        return JsonSupport.write(node);
    }

    private String anomaly(String status, long streamTimestamp, OfflineState state)
            throws Exception {
        Identity id = identity.value();
        ObjectNode node = JsonSupport.object();
        node.put("schema_version", 1);
        node.put("anomaly_id", state.anomalyId);
        node.put("run_id", id.runId);
        node.put("robot_id", id.robotId);
        node.putNull("topic");
        node.put("condition_type", "ROBOT_OFFLINE");
        node.put("status", status);
        node.put("severity", "error");
        node.put("revision", state.revision);
        node.put("effective_start_stream_ms", state.startMs);
        node.put("detected_stream_ms", streamTimestamp);
        if ("recovered".equals(status)) node.put("recovered_stream_ms", streamTimestamp);
        else node.putNull("recovered_stream_ms");
        node.putObject("evidence").put("processing_silence_ms", OFFLINE_AFTER_MS);
        return JsonSupport.write(node);
    }

    public static final class Identity implements Serializable {
        public String runId;
        public String robotId;
        public long startStreamMs;
        public Identity() {}
    }

    public static final class OfflineState implements Serializable {
        public String anomalyId;
        public long startMs;
        public int revision;
        public OfflineState() {}
    }
}
