package io.github.mikehstudio.rostelemetry;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.List;
import org.apache.flink.api.common.typeinfo.Types;
import org.apache.flink.runtime.checkpoint.OperatorSubtaskState;
import org.apache.flink.streaming.api.functions.KeyedProcessFunction;
import org.apache.flink.streaming.api.operators.KeyedProcessOperator;
import org.apache.flink.streaming.api.watermark.Watermark;
import org.apache.flink.streaming.runtime.streamrecord.StreamRecord;
import org.apache.flink.streaming.util.KeyedOneInputStreamOperatorTestHarness;
import org.junit.jupiter.api.Test;

final class StateLifetimeHarnessTest {
    private static final long THIRTEEN_MINUTES = 13 * 60_000L;

    @Test
    void inactivityConfigurationUsesDocumentedDefaultAndRejectsUnsafeValues() {
        assertEquals(StreamingDefaults.RUN_STATE_IDLE_TIMEOUT_MS, RunStateRetention.parseIdleTimeoutMs(null));
        assertEquals(StreamingDefaults.RUN_STATE_IDLE_TIMEOUT_MS, RunStateRetention.parseIdleTimeoutMs(" "));
        assertEquals(30_000, RunStateRetention.parseIdleTimeoutMs(" 30000 "));
        for (String invalid : List.of("0", "-1", "5000", "10000", "NaN", "9223372036854775808")) {
            assertThrows(IllegalArgumentException.class, () -> RunStateRetention.parseIdleTimeoutMs(invalid));
        }
    }

    @Test
    void longActiveRunRetainsRegistrationDedupeAndFullSummary() throws Exception {
        try (TopicHarness harness = new TopicHarness()) {
            harness.process(registration());
            harness.process(telemetry(0));
            for (int minute = 1; minute <= 26; minute++) {
                harness.clock(minute * 60_000L);
                harness.process(telemetry(minute * 60_000L));
            }
            harness.process(telemetry(0));
            harness.process(envelope("run_ended", 26 * 60_000L));
            harness.watermark(26 * 60_000L + StreamingDefaults.ALLOWED_LATENESS_MS);
            JsonNode summary = harness.values().stream()
                    .filter(node -> node.path("metric_type").asText().equals("mission_summary"))
                    .findFirst().orElseThrow();
            assertEquals(27, summary.path("payload").path("message_count").asInt());
            var rejected = harness.delegate.getSideOutput(TopicHealthProcessor.LATE_EVENTS);
            assertEquals(1, rejected.size());
            assertEquals("duplicate", read(rejected.peek().getValue()).path("reason").asText());
            assertEquals(0, harness.delegate.numKeyedStateEntries());
            assertEquals(0, harness.delegate.numProcessingTimeTimers());
        }
    }

    @Test
    void longPauseRetainsFirstEventAndResumesWithoutUnregisteredRejection() throws Exception {
        try (TopicHarness harness = new TopicHarness()) {
            harness.process(registration());
            harness.process(telemetry(0));
            harness.process(envelope("run_paused", 1));
            harness.clock(THIRTEEN_MINUTES);
            harness.process(envelope("run_resumed", 1));
            harness.process(telemetry(2));
            harness.process(envelope("run_ended", 3));
            harness.watermark(3 + StreamingDefaults.ALLOWED_LATENESS_MS);
            JsonNode summary = harness.values().stream()
                    .filter(node -> node.path("metric_type").asText().equals("mission_summary"))
                    .findFirst().orElseThrow();
            assertEquals(2, summary.path("payload").path("message_count").asInt());
            assertTrue(harness.delegate.getSideOutput(TopicHealthProcessor.LATE_EVENTS) == null);
        }
    }

    @Test
    void checkpointRestoresPausedEvidenceAndInactivityDeadline() throws Exception {
        OperatorSubtaskState snapshot;
        try (TopicHarness original = new TopicHarness()) {
            original.process(registration());
            original.process(telemetry(0));
            original.process(envelope("run_paused", 1));
            snapshot = original.delegate.snapshot(1, 0);
        }
        try (TopicHarness restored = new TopicHarness(snapshot)) {
            restored.clock(THIRTEEN_MINUTES);
            restored.process(envelope("run_resumed", 1));
            restored.process(telemetry(2));
            restored.process(envelope("run_ended", 3));
            restored.watermark(3 + StreamingDefaults.ALLOWED_LATENESS_MS);
            JsonNode summary = restored.values().stream()
                    .filter(node -> node.path("metric_type").asText().equals("mission_summary"))
                    .findFirst().orElseThrow();
            assertEquals(2, summary.path("payload").path("message_count").asInt());
            assertEquals(0, restored.delegate.numKeyedStateEntries());
        }
        try (TopicHarness abandoned = new TopicHarness(snapshot)) {
            abandoned.clock(StreamingDefaults.RUN_STATE_IDLE_TIMEOUT_MS);
            assertEquals(0, abandoned.delegate.numKeyedStateEntries());
            assertEquals(0, abandoned.delegate.numProcessingTimeTimers());
        }
    }

    @Test
    void abandonedPausedRunClearsAllStateAndTimers() throws Exception {
        try (TopicHarness harness = new TopicHarness()) {
            harness.process(registration());
            harness.process(telemetry(0));
            harness.process(envelope("run_paused", 1));
            harness.clock(StreamingDefaults.RUN_STATE_IDLE_TIMEOUT_MS);
            assertEquals(0, harness.delegate.numKeyedStateEntries());
            assertEquals(0, harness.delegate.numEventTimeTimers());
            assertEquals(0, harness.delegate.numProcessingTimeTimers());
            assertTrue(harness.values().isEmpty());
        }
    }

    @Test
    void activityRenewsWholeRunBeyondAbandonmentBoundAndAbortClearsIt() throws Exception {
        try (TopicHarness harness = new TopicHarness()) {
            harness.process(registration());
            harness.process(telemetry(0));
            harness.clock(StreamingDefaults.RUN_STATE_IDLE_TIMEOUT_MS - 1);
            harness.process(telemetry(1));
            harness.clock(StreamingDefaults.RUN_STATE_IDLE_TIMEOUT_MS + 1);
            harness.process(telemetry(2));
            assertTrue(harness.delegate.getSideOutput(TopicHealthProcessor.LATE_EVENTS) == null);
            harness.process(envelope("run_aborted", 3));
            assertEquals(0, harness.delegate.numKeyedStateEntries());
            assertEquals(0, harness.delegate.numEventTimeTimers());
            assertEquals(0, harness.delegate.numProcessingTimeTimers());
        }
    }

    @Test
    void livenessIdentityAndWatchdogSurviveLongPauseThenCleanupAtEnd() throws Exception {
        try (var harness = envelopeHarness(new RobotLivenessProcessor(StreamingDefaults.RUN_STATE_IDLE_TIMEOUT_MS))) {
            harness.processElement(new StreamRecord<>(envelope("run_started", 0)));
            harness.processElement(new StreamRecord<>(envelope("run_paused", 1)));
            clock(harness, THIRTEEN_MINUTES);
            harness.processElement(new StreamRecord<>(envelope("run_resumed", 1)));
            clock(harness, THIRTEEN_MINUTES + StreamingDefaults.WHOLE_ROBOT_SILENCE_MS);
            var anomalies = harness.getSideOutput(RobotLivenessProcessor.ANOMALIES);
            assertEquals(1, anomalies.size());
            assertEquals("ROBOT_OFFLINE", read(anomalies.peek().getValue()).path("condition_type").asText());
            harness.processElement(new StreamRecord<>(envelope("run_ended", 2)));
            assertEquals(0, harness.numKeyedStateEntries());
            assertEquals(0, harness.numProcessingTimeTimers());
        }
    }

    @Test
    void sequenceEvidenceSurvivesLongPauseWithoutForgettingDuplicates() throws Exception {
        try (var harness = envelopeHarness(new SequenceEvidenceProcessor(StreamingDefaults.RUN_STATE_IDLE_TIMEOUT_MS))) {
            harness.processElement(new StreamRecord<>(telemetry(1)));
            harness.processElement(new StreamRecord<>(envelope("run_paused", 1)));
            clock(harness, THIRTEEN_MINUTES);
            harness.processElement(new StreamRecord<>(envelope("run_resumed", 1)));
            harness.processElement(new StreamRecord<>(telemetry(1)));
            harness.processElement(new StreamRecord<>(telemetry(3)));
            assertEquals(1, harness.extractOutputValues().size());
            assertEquals("sequence_gap", read(harness.extractOutputValues().get(0)).path("reason").asText());
            harness.processElement(new StreamRecord<>(envelope("run_ended", 4)));
            assertEquals(0, harness.numKeyedStateEntries());
            assertEquals(0, harness.numProcessingTimeTimers());
        }
    }

    @Test
    void activeConditionDoesNotDisappearDuringLongMissionAndIdleCleanupIsBounded() throws Exception {
        try (var harness = new KeyedOneInputStreamOperatorTestHarness<String, String, String>(
                new KeyedProcessOperator<>(new RobotHealthProcessor(StreamingDefaults.RUN_STATE_IDLE_TIMEOUT_MS)), ignored -> "run-1|robot-17", Types.STRING)) {
            harness.open();
            harness.setStateTtlProcessingTime(0);
            ObjectNode anomaly = envelope("unused", 0);
            anomaly.put("anomaly_id", "gap-1");
            anomaly.put("condition_type", "GAP");
            anomaly.put("status", "active");
            harness.processElement(new StreamRecord<>(JsonSupport.write(anomaly)));
            harness.setStateTtlProcessingTime(THIRTEEN_MINUTES);
            harness.setProcessingTime(THIRTEEN_MINUTES);
            ObjectNode window = envelope("unused", 1);
            window.put("metric_type", "topic_window");
            window.putObject("payload").put("recovery_in_progress", false);
            harness.processElement(new StreamRecord<>(JsonSupport.write(window)));
            var values = harness.extractOutputValues();
            assertEquals("degraded", read(values.get(values.size() - 1)).path("payload").path("status").asText());
            harness.setProcessingTime(THIRTEEN_MINUTES + StreamingDefaults.RUN_STATE_IDLE_TIMEOUT_MS);
            assertEquals(0, harness.numKeyedStateEntries());
            assertEquals(0, harness.numProcessingTimeTimers());
        }
    }

    private static KeyedOneInputStreamOperatorTestHarness<String, JsonNode, String> envelopeHarness(
            KeyedProcessFunction<String, JsonNode, String> processor) throws Exception {
        var harness = new KeyedOneInputStreamOperatorTestHarness<String, JsonNode, String>(
                new KeyedProcessOperator<>(processor), ignored -> "run-1|robot-17", Types.STRING);
        harness.open();
        clock(harness, 0);
        return harness;
    }

    private static void clock(KeyedOneInputStreamOperatorTestHarness<String, JsonNode, String> harness,
                              long timestamp) throws Exception {
        harness.setStateTtlProcessingTime(timestamp);
        harness.setProcessingTime(timestamp);
    }

    private static ObjectNode registration() {
        ObjectNode node = envelope("topic_registered", 0);
        node.put("event_timestamp_ns", 0);
        ObjectNode body = (ObjectNode) node.path("body");
        body.put("expected_rate_hz", 1.0);
        body.put("rate_monitoring_enabled", false);
        body.put("startup_grace_ms", 2000);
        body.put("dropout_threshold_ms", 5000);
        return node;
    }

    private static ObjectNode telemetry(long timestamp) {
        ObjectNode node = envelope("telemetry", timestamp);
        ObjectNode body = (ObjectNode) node.path("body");
        body.put("event_id", "event-" + timestamp);
        body.put("sequence", timestamp);
        body.put("event_timestamp_ns", timestamp * 1_000_000L);
        return node;
    }

    private static ObjectNode envelope(String type, long timestamp) {
        ObjectNode node = JsonSupport.object();
        node.put("envelope_type", type);
        node.put("run_id", "run-1");
        node.put("robot_id", "robot-17");
        node.put("topic", "/camera/image_raw");
        node.put("stream_timestamp_ms", timestamp);
        node.putObject("body").put("replay_rate", 1);
        return node;
    }

    private static JsonNode read(String value) {
        try { return JsonSupport.MAPPER.readTree(value); }
        catch (Exception error) { throw new IllegalArgumentException(error); }
    }

    private static final class TopicHarness implements AutoCloseable {
        final TimerAwareOperator operator = new TimerAwareOperator();
        final KeyedOneInputStreamOperatorTestHarness<String, JsonNode, String> delegate;

        TopicHarness() throws Exception { this(null); }

        TopicHarness(OperatorSubtaskState snapshot) throws Exception {
            delegate = new KeyedOneInputStreamOperatorTestHarness<>(
                    operator, ignored -> "run-1|robot-17|/camera/image_raw", Types.STRING);
            if (snapshot != null) delegate.initializeState(snapshot);
            delegate.open();
            clock(0);
        }
        void process(JsonNode node) throws Exception { delegate.processElement(new StreamRecord<>(node)); }
        void clock(long timestamp) throws Exception {
            // Flink's TTL clock is independent of the processing-time timer clock in this harness.
            delegate.setStateTtlProcessingTime(timestamp);
            delegate.setProcessingTime(timestamp);
        }
        void watermark(long timestamp) throws Exception {
            operator.advanceEventTime(timestamp);
            delegate.processWatermark(timestamp);
        }
        List<JsonNode> values() { return delegate.extractOutputValues().stream().map(StateLifetimeHarnessTest::read).toList(); }
        @Override public void close() throws Exception { delegate.close(); }
    }

    private static final class TimerAwareOperator extends KeyedProcessOperator<String, JsonNode, String> {
        TimerAwareOperator() { super(new TopicHealthProcessor(StreamingDefaults.RUN_STATE_IDLE_TIMEOUT_MS)); }
        void advanceEventTime(long timestamp) throws Exception {
            getTimeServiceManager().orElseThrow().advanceWatermark(new Watermark(timestamp));
        }
    }
}
