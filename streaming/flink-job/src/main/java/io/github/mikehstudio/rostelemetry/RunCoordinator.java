package io.github.mikehstudio.rostelemetry;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.apache.flink.api.common.functions.OpenContext;
import org.apache.flink.api.common.state.MapState;
import org.apache.flink.api.common.state.MapStateDescriptor;
import org.apache.flink.api.common.state.StateTtlConfig;
import org.apache.flink.api.common.state.ValueState;
import org.apache.flink.api.common.state.ValueStateDescriptor;
import org.apache.flink.streaming.api.functions.KeyedProcessFunction;
import org.apache.flink.util.Collector;

/** Emits RUNNING only after all four topic registrations have reached Flink. */
final class RunCoordinator extends KeyedProcessFunction<String, JsonNode, String> {
    private static final int EXPECTED_TOPIC_COUNT = StreamingDefaults.EXPECTED_TOPIC_COUNT;
    private transient MapState<String, Boolean> registrations;
    private transient ValueState<Boolean> emitted;

    @Override
    public void open(OpenContext ignored) {
        StateTtlConfig ttl = StreamingDefaults.stateTtl();
        MapStateDescriptor<String, Boolean> registrationDescriptor =
                new MapStateDescriptor<>("run-registrations-v1", String.class, Boolean.class);
        registrationDescriptor.enableTimeToLive(ttl);
        registrations = getRuntimeContext().getMapState(registrationDescriptor);
        ValueStateDescriptor<Boolean> emittedDescriptor =
                new ValueStateDescriptor<>("run-registration-ready-v1", Boolean.class);
        emittedDescriptor.enableTimeToLive(ttl);
        emitted = getRuntimeContext().getState(emittedDescriptor);
    }

    @Override
    public void processElement(JsonNode envelope, Context context, Collector<String> output)
            throws Exception {
        registrations.put(envelope.path("topic").asText(), true);
        int count = 0;
        for (Boolean ignored : registrations.values()) count++;
        if (count == EXPECTED_TOPIC_COUNT && !Boolean.TRUE.equals(emitted.value())) {
            emitted.update(true);
            output.collect(statusMetric(envelope, "running", "all_topics_registered", 1));
            registrations.clear();
        }
    }

    static String statusMetric(JsonNode envelope, String status, String source, int revision) {
        long timestamp = envelope.path("stream_timestamp_ms").asLong();
        ObjectNode node = JsonSupport.object();
        node.put("schema_version", 1);
        node.put("metric_id", JsonSupport.sha256(
                1, envelope.path("run_id").asText(), envelope.path("robot_id").asText(),
                "run_status", status, timestamp, revision));
        node.put("metric_type", "run_status");
        node.put("run_id", envelope.path("run_id").asText());
        node.put("robot_id", envelope.path("robot_id").asText());
        node.putNull("topic");
        node.putNull("window_start_ms");
        node.putNull("window_end_ms");
        node.put("revision", revision);
        node.put("stream_timestamp_ms", timestamp);
        ObjectNode payload = node.putObject("payload");
        payload.put("status", status);
        payload.put("source", "recorded_replay");
        payload.put("reason", source);
        return JsonSupport.write(node);
    }
}
