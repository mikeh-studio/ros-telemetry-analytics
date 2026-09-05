package io.github.mikehstudio.rostelemetry;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.apache.flink.api.common.functions.OpenContext;
import org.apache.flink.api.common.state.MapState;
import org.apache.flink.api.common.state.MapStateDescriptor;
import org.apache.flink.api.common.state.ValueState;
import org.apache.flink.api.common.state.ValueStateDescriptor;
import org.apache.flink.streaming.api.functions.KeyedProcessFunction;
import org.apache.flink.util.Collector;

/** Records global bag-sequence gaps and regressions without changing analytical state. */
final class SequenceEvidenceProcessor extends KeyedProcessFunction<String, JsonNode, String> {
    private final long idleTimeoutMs;
    private transient RunStateRetention retention;
    private transient ValueState<Long> maximumSequence;
    private transient MapState<String, Boolean> seenEventIds;

    SequenceEvidenceProcessor() {
        this(RunStateRetention.configuredIdleTimeoutMs());
    }

    SequenceEvidenceProcessor(long idleTimeoutMs) {
        this.idleTimeoutMs = idleTimeoutMs;
    }

    @Override
    public void open(OpenContext ignored) {
        retention = new RunStateRetention(getRuntimeContext(), idleTimeoutMs);
        ValueStateDescriptor<Long> maximum =
                new ValueStateDescriptor<>("global-maximum-sequence-v1", Long.class);
        maximumSequence = getRuntimeContext().getState(maximum);
        MapStateDescriptor<String, Boolean> seen =
                new MapStateDescriptor<>("global-seen-sequence-events-v1", String.class, Boolean.class);
        seenEventIds = getRuntimeContext().getMapState(seen);
    }

    @Override
    public void processElement(JsonNode envelope, Context context, Collector<String> output)
            throws Exception {
        retention.touch(context.timerService());
        String type = envelope.path("envelope_type").asText();
        if (type.equals("run_ended") || type.equals("run_aborted") || type.equals("run_failed")) {
            clearState();
            retention.clear(context.timerService());
            return;
        }
        if (!type.equals("telemetry")) return;
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

    @Override
    public void onTimer(long timestamp, OnTimerContext context, Collector<String> output)
            throws Exception {
        if (retention.expires(timestamp)) {
            clearState();
            retention.clear(context.timerService());
        }
    }

    private void clearState() {
        maximumSequence.clear();
        seenEventIds.clear();
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
