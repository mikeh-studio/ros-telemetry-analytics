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

/** Turns four durable-topic summary records into one run-level summary-ready signal. */
final class SummaryCoordinator extends KeyedProcessFunction<String, String, String> {
    private static final int EXPECTED_TOPIC_COUNT = StreamingDefaults.EXPECTED_TOPIC_COUNT;
    private transient MapState<String, Boolean> summaries;
    private transient ValueState<Boolean> emitted;

    @Override
    public void open(OpenContext ignored) {
        StateTtlConfig ttl = StreamingDefaults.stateTtl();
        MapStateDescriptor<String, Boolean> summaryDescriptor =
                new MapStateDescriptor<>("summary-topics-v1", String.class, Boolean.class);
        summaryDescriptor.enableTimeToLive(ttl);
        summaries = getRuntimeContext().getMapState(summaryDescriptor);
        ValueStateDescriptor<Boolean> emittedDescriptor =
                new ValueStateDescriptor<>("summary-ready-v1", Boolean.class);
        emittedDescriptor.enableTimeToLive(ttl);
        emitted = getRuntimeContext().getState(emittedDescriptor);
    }

    @Override
    public void processElement(String value, Context context, Collector<String> output)
            throws Exception {
        JsonNode summary = JsonSupport.MAPPER.readTree(value);
        summaries.put(summary.path("topic").asText(), true);
        int count = 0;
        for (Boolean ignored : summaries.values()) count++;
        if (count != EXPECTED_TOPIC_COUNT || Boolean.TRUE.equals(emitted.value())) return;
        emitted.update(true);
        long timestamp = summary.path("stream_timestamp_ms").asLong();
        ObjectNode node = JsonSupport.object();
        node.put("schema_version", 1);
        node.put("metric_id", JsonSupport.sha256(
                1, summary.path("run_id").asText(), summary.path("robot_id").asText(),
                "run_status", "summary_ready", timestamp, 0));
        node.put("metric_type", "run_status");
        node.put("run_id", summary.path("run_id").asText());
        node.put("robot_id", summary.path("robot_id").asText());
        node.putNull("topic");
        node.putNull("window_start_ms");
        node.putNull("window_end_ms");
        node.put("revision", 0);
        node.put("stream_timestamp_ms", timestamp);
        ObjectNode payload = node.putObject("payload");
        payload.put("status", "summary_ready");
        payload.put("source", "recorded_replay");
        payload.put("summary_topic_count", EXPECTED_TOPIC_COUNT);
        output.collect(JsonSupport.write(node));
        summaries.clear();
    }

}
