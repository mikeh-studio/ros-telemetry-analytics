package io.github.mikehstudio.rostelemetry;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.Serializable;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import org.apache.flink.api.common.functions.OpenContext;
import org.apache.flink.api.common.state.MapState;
import org.apache.flink.api.common.state.MapStateDescriptor;
import org.apache.flink.api.common.state.ValueState;
import org.apache.flink.api.common.state.ValueStateDescriptor;
import org.apache.flink.streaming.api.functions.KeyedProcessFunction;
import org.apache.flink.util.Collector;

/** Derives robot health from independent active conditions and their recovery gates. */
final class RobotHealthProcessor extends KeyedProcessFunction<String, String, String> {
    private final long idleTimeoutMs;
    private transient RunStateRetention retention;
    private transient MapState<String, ActiveCondition> conditions;
    private transient MapState<String, Boolean> topicRecovery;
    private transient ValueState<Boolean> robotRecovery;

    RobotHealthProcessor() {
        this(RunStateRetention.configuredIdleTimeoutMs());
    }

    RobotHealthProcessor(long idleTimeoutMs) {
        this.idleTimeoutMs = idleTimeoutMs;
    }

    @Override
    public void open(OpenContext ignored) {
        retention = new RunStateRetention(getRuntimeContext(), idleTimeoutMs);
        MapStateDescriptor<String, ActiveCondition> conditionDescriptor =
                new MapStateDescriptor<>(
                        "robot-active-conditions-v3", String.class, ActiveCondition.class);
        conditions = getRuntimeContext().getMapState(conditionDescriptor);
        MapStateDescriptor<String, Boolean> recoveryDescriptor =
                new MapStateDescriptor<>(
                        "robot-topic-recovery-v3", String.class, Boolean.class);
        topicRecovery = getRuntimeContext().getMapState(recoveryDescriptor);
        ValueStateDescriptor<Boolean> robotRecoveryDescriptor =
                new ValueStateDescriptor<>("robot-offline-recovery-v3", Boolean.class);
        robotRecovery = getRuntimeContext().getState(robotRecoveryDescriptor);
    }

    @Override
    public void processElement(String value, Context context, Collector<String> output)
            throws Exception {
        retention.touch(context.timerService());
        JsonNode signal = JsonSupport.MAPPER.readTree(value);
        if (signal.has("anomaly_id")) updateCondition(signal);
        else if (signal.path("metric_type").asText().equals("topic_window")) {
            topicRecovery.put(
                    signal.path("topic").asText(),
                    signal.path("payload").path("recovery_in_progress").asBoolean(false));
        } else if (signal.path("metric_type").asText().equals("robot_health")) {
            robotRecovery.update(
                    signal.path("payload").path("status").asText().equals("recovering"));
        }
        output.collect(metric(signal));
    }

    @Override
    public void onTimer(long timestamp, OnTimerContext context, Collector<String> output)
            throws Exception {
        if (retention.expires(timestamp)) {
            clearState();
            retention.clear(context.timerService());
        }
    }

    private void clearState() {
        conditions.clear();
        topicRecovery.clear();
        robotRecovery.clear();
    }

    private void updateCondition(JsonNode anomaly) throws Exception {
        String key = conditionKey(anomaly);
        if (anomaly.path("status").asText().equals("recovered")) {
            conditions.remove(key);
            if (anomaly.path("condition_type").asText().equals("ROBOT_OFFLINE")) {
                robotRecovery.update(false);
            }
            return;
        }
        ActiveCondition condition = new ActiveCondition();
        condition.anomalyId = anomaly.path("anomaly_id").asText();
        condition.conditionType = anomaly.path("condition_type").asText();
        condition.topic = anomaly.path("topic").isNull()
                ? null
                : anomaly.path("topic").asText();
        condition.detectedStreamMs = anomaly.path("detected_stream_ms").asLong();
        conditions.put(key, condition);
    }

    private String metric(JsonNode signal) throws Exception {
        long timestamp = signal.path("stream_timestamp_ms").asLong(
                signal.path("detected_stream_ms").asLong());
        String status = aggregateStatus();
        ActiveCondition primary = primaryCondition();
        ObjectNode result = JsonSupport.object();
        result.put("schema_version", 1);
        result.put("metric_id", JsonSupport.sha256(
                1,
                signal.path("run_id").asText(),
                signal.path("robot_id").asText(),
                "robot_health",
                timestamp,
                status,
                primary == null ? "none" : primary.anomalyId));
        result.put("metric_type", "robot_health");
        result.put("run_id", signal.path("run_id").asText());
        result.put("robot_id", signal.path("robot_id").asText());
        result.putNull("topic");
        result.putNull("window_start_ms");
        result.put("window_end_ms", timestamp);
        result.put("revision", 0);
        result.put("stream_timestamp_ms", timestamp);
        ObjectNode payload = result.putObject("payload");
        payload.put("status", status);
        payload.put("active_condition_count", conditionCount());
        if (primary == null) payload.putNull("primary_anomaly");
        else {
            ObjectNode primaryNode = payload.putObject("primary_anomaly");
            primaryNode.put("anomaly_id", primary.anomalyId);
            primaryNode.put("condition_type", primary.conditionType);
            if (primary.topic == null) primaryNode.putNull("topic");
            else primaryNode.put("topic", primary.topic);
            primaryNode.put("detected_stream_ms", primary.detectedStreamMs);
        }
        return JsonSupport.write(result);
    }

    private String aggregateStatus() throws Exception {
        if (hasCondition("ROBOT_OFFLINE")) return "offline";
        if (conditions.isEmpty()) return "healthy";
        if (recoveryActive()) return "recovering";
        return "degraded";
    }

    private boolean recoveryActive() throws Exception {
        if (Boolean.TRUE.equals(robotRecovery.value()) && hasCondition("ROBOT_OFFLINE")) {
            return true;
        }
        for (ActiveCondition condition : conditions.values()) {
            if (condition.topic != null
                    && Boolean.TRUE.equals(topicRecovery.get(condition.topic))) return true;
        }
        return false;
    }

    private boolean hasCondition(String type) throws Exception {
        for (ActiveCondition condition : conditions.values()) {
            if (condition.conditionType.equals(type)) return true;
        }
        return false;
    }

    private ActiveCondition primaryCondition() throws Exception {
        List<ActiveCondition> active = new ArrayList<>();
        for (ActiveCondition condition : conditions.values()) active.add(condition);
        return active.stream()
                .min(Comparator.comparingInt(
                                (ActiveCondition condition) -> priority(condition.conditionType))
                        .thenComparingLong(condition -> condition.detectedStreamMs)
                        .thenComparing(condition -> condition.topic == null ? "" : condition.topic))
                .orElse(null);
    }

    private int conditionCount() throws Exception {
        int count = 0;
        for (ActiveCondition ignored : conditions.values()) count++;
        return count;
    }

    private static int priority(String condition) {
        return switch (condition) {
            case "ROBOT_OFFLINE" -> 0;
            case "NEVER_SEEN" -> 1;
            case "GAP" -> 2;
            case "RATE" -> 3;
            default -> 4;
        };
    }

    private static String conditionKey(JsonNode anomaly) {
        return anomaly.path("topic").asText("__robot__")
                + "|"
                + anomaly.path("condition_type").asText();
    }

    public static final class ActiveCondition implements Serializable {
        public String anomalyId;
        public String conditionType;
        public String topic;
        public long detectedStreamMs;

        public ActiveCondition() {}
    }
}
