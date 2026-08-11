package io.github.mikehstudio.rostelemetry;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.time.Duration;
import org.apache.flink.api.common.functions.OpenContext;
import org.apache.flink.api.common.state.MapState;
import org.apache.flink.api.common.state.MapStateDescriptor;
import org.apache.flink.api.common.state.StateTtlConfig;
import org.apache.flink.api.common.state.ValueState;
import org.apache.flink.api.common.state.ValueStateDescriptor;
import org.apache.flink.streaming.api.functions.KeyedProcessFunction;
import org.apache.flink.util.Collector;

/** Records global bag-sequence gaps and regressions without changing analytical state. */
final class SequenceEvidenceProcessor extends KeyedProcessFunction<String, JsonNode, String> {
    private transient ValueState<Long> maximumSequence;
    private transient MapState<String, Boolean> seenEventIds;

    @Override
    public void open(OpenContext ignored) {
        StateTtlConfig ttl = StateTtlConfig.newBuilder(
                        Duration.ofMinutes(StreamingDefaults.STATE_TTL_MINUTES))
                .setUpdateType(StateTtlConfig.UpdateType.OnCreateAndWrite)
                .neverReturnExpired()
                .build();
        ValueStateDescriptor<Long> maximum =
                new ValueStateDescriptor<>("global-maximum-sequence-v1", Long.class);
        maximum.enableTimeToLive(ttl);
        maximumSequence = getRuntimeContext().getState(maximum);
        MapStateDescriptor<String, Boolean> seen =
                new MapStateDescriptor<>("global-seen-sequence-events-v1", String.class, Boolean.class);
        seen.enableTimeToLive(ttl);
        seenEventIds = getRuntimeContext().getMapState(seen);
    }

    @Override
    public void processElement(JsonNode envelope, Context context, Collector<String> output)
            throws Exception {
        JsonNode body = envelope.path("body");
        String eventId = body.path("event_id").asText();
        if (seenEventIds.contains(eventId)) return;
        seenEventIds.put(eventId, true);

        long observed = body.path("sequence").asLong();
        Long maximum = maximumSequence.value();
        if (maximum != null && observed > maximum + 1) {
            output.collect(evidence(envelope, "sequence_gap", maximum + 1, observed));
        } else if (maximum != null && observed <= maximum) {
            output.collect(evidence(envelope, "sequence_regression", maximum + 1, observed));
        }
        if (maximum == null || observed > maximum) maximumSequence.update(observed);
    }

    private static String evidence(
            JsonNode envelope, String reason, long expectedNext, long observed) {
        ObjectNode node = JsonSupport.object();
        node.put("schema_version", 1);
        node.put("reason", reason);
        node.put("event_id", envelope.path("body").path("event_id").asText());
        node.put("run_id", envelope.path("run_id").asText());
        node.put("robot_id", envelope.path("robot_id").asText());
        node.put("topic", envelope.path("topic").asText());
        node.put("expected_next_sequence", expectedNext);
        node.put("observed_sequence", observed);
        node.put("stream_timestamp_ms", envelope.path("stream_timestamp_ms").asLong());
        return JsonSupport.write(node);
    }
}
