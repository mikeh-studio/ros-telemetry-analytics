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

/** Emits RUNNING only after every dataset topic registration has reached Flink. */
final class RunCoordinator extends KeyedProcessFunction<String, JsonNode, String> {
    private static final int EXPECTED_TOPIC_COUNT = StreamingDefaults.EXPECTED_TOPIC_COUNT;
    private transient MapState<String, Boolean> registrations;
    private transient ValueState<Boolean> emitted;
    private transient ValueState<Integer> expectedTopicCount;

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
        ValueStateDescriptor<Integer> expectedCountDescriptor =
                new ValueStateDescriptor<>("run-expected-topic-count-v1", Integer.class);
        expectedCountDescriptor.enableTimeToLive(ttl);
        expectedTopicCount = getRuntimeContext().getState(expectedCountDescriptor);
    }

    @Override
    public void processElement(JsonNode envelope, Context context, Collector<String> output)
            throws Exception {
        registrations.put(envelope.path("topic").asText(), true);
        int advertisedCount = envelope.path("body").path("expected_topic_count")
                .asInt(EXPECTED_TOPIC_COUNT);
        Integer existingCount = expectedTopicCount.value();
        if (advertisedCount <= 0) throw new IllegalArgumentException("expected_topic_count must be positive");
        if (existingCount != null && existingCount != advertisedCount) {
            throw new IllegalArgumentException("inconsistent expected_topic_count registrations");
        }
        expectedTopicCount.update(advertisedCount);
        int count = 0;
        for (Boolean ignored : registrations.values()) count++;
        if (count == advertisedCount && !Boolean.TRUE.equals(emitted.value())) {
            emitted.update(true);
            output.collect(statusMetric(envelope, "running", "all_topics_registered", 1));
            registrations.clear();
            expectedTopicCount.clear();
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
        JsonNode body = envelope.path("body");
        copyText(body, payload, "dataset_id");
        copyText(body, payload, "dataset_name");
        copyText(body, payload, "source_format");
        if (body.has("mission_duration_ms")) {
            payload.put("mission_duration_ms", body.path("mission_duration_ms").asLong());
        }
        payload.put("expected_topic_count", body.path("expected_topic_count")
                .asInt(EXPECTED_TOPIC_COUNT));
        return JsonSupport.write(node);
    }

    private static void copyText(JsonNode source, ObjectNode destination, String field) {
        if (source.hasNonNull(field)) destination.put(field, source.path(field).asText());
    }
}
