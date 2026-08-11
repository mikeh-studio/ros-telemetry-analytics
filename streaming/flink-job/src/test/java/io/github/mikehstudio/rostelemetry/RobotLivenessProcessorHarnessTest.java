package io.github.mikehstudio.rostelemetry;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.List;
import org.apache.flink.api.common.typeinfo.Types;
import org.apache.flink.streaming.api.operators.KeyedProcessOperator;
import org.apache.flink.streaming.api.watermark.Watermark;
import org.apache.flink.streaming.runtime.streamrecord.StreamRecord;
import org.apache.flink.streaming.util.KeyedOneInputStreamOperatorTestHarness;
import org.junit.jupiter.api.Test;

final class RobotLivenessProcessorHarnessTest {
    @Test
    void oneXWatchdogOpensOfflineAndRecoversAfterThreeAcceptedEvents() throws Exception {
        try (Harness harness = harness()) {
            harness.process(lifecycle("run_started", 100_000, 1));
            harness.process(telemetry("event-0", 100_000));
            harness.processingTime(9_999);
            assertTrue(harness.anomalies().isEmpty());

            harness.processingTime(10_000);
            List<JsonNode> active = harness.anomalies();
            assertEquals(1, active.size());
            assertEquals("ROBOT_OFFLINE", active.get(0).path("condition_type").asText());
            assertEquals("active", active.get(0).path("status").asText());
            String anomalyId = active.get(0).path("anomaly_id").asText();
            assertEquals(
                    JsonSupport.sha256(
                            "run-1", "robot-17", "__robot__", "ROBOT_OFFLINE", 110_000),
                    anomalyId);

            harness.watermark(110_000);
            harness.process(telemetry("late-1", 109_999));
            harness.process(telemetry("late-2", 109_999));
            harness.process(telemetry("late-3", 109_999));
            assertEquals(1, harness.anomalies().size());

            harness.process(telemetry("event-1", 110_000));
            harness.process(telemetry("event-2", 110_040));
            harness.process(telemetry("event-3", 110_080));
            List<JsonNode> transitions = harness.anomalies();
            assertEquals(2, transitions.size());
            assertEquals(anomalyId, transitions.get(1).path("anomaly_id").asText());
            assertEquals("recovered", transitions.get(1).path("status").asText());
            assertEquals(1, transitions.get(1).path("revision").asInt());
            assertEquals("healthy", harness.metrics().get(harness.metrics().size() - 1)
                    .path("payload").path("status").asText());
        }
    }

    @Test
    void pauseAndFiveXReplayDisableTheProcessingTimeWatchdog() throws Exception {
        try (Harness paused = harness()) {
            paused.process(lifecycle("run_started", 100_000, 1));
            paused.process(lifecycle("run_paused", 100_000, 1));
            paused.processingTime(20_000);
            assertTrue(paused.anomalies().isEmpty());
        }
        try (Harness accelerated = harness()) {
            accelerated.process(lifecycle("run_started", 100_000, 5));
            accelerated.processingTime(20_000);
            assertTrue(accelerated.anomalies().isEmpty());
            assertEquals(
                    false,
                    accelerated.metrics().get(0).path("payload").path("watchdog_enabled")
                            .asBoolean());
        }
        try (Harness failed = harness()) {
            failed.process(lifecycle("run_started", 100_000, 1));
            failed.process(lifecycle("run_failed", 101_000, 1));
            failed.processingTime(20_000);
            assertTrue(failed.anomalies().isEmpty());
        }
    }

    private static Harness harness() throws Exception {
        KeyedProcessOperator<String, JsonNode, String> operator =
                new KeyedProcessOperator<>(new RobotLivenessProcessor());
        KeyedOneInputStreamOperatorTestHarness<String, JsonNode, String> delegate =
                new KeyedOneInputStreamOperatorTestHarness<>(
                        operator,
                        node -> {
                            return node.path("run_id").asText()
                                    + "|"
                                    + node.path("robot_id").asText();
                        },
                        Types.STRING);
        delegate.open();
        return new Harness(delegate);
    }

    private static JsonNode lifecycle(String type, long timestamp, int replayRate) {
        ObjectNode node = base(type, timestamp);
        node.putObject("body").put("replay_rate", replayRate);
        return node;
    }

    private static JsonNode telemetry(String eventId, long timestamp) {
        ObjectNode node = base("telemetry", timestamp);
        node.putObject("body").put("event_id", eventId);
        return node;
    }

    private static ObjectNode base(String type, long timestamp) {
        ObjectNode node = JsonSupport.object();
        node.put("schema_version", 1);
        node.put("envelope_id", JsonSupport.sha256(type, timestamp));
        node.put("envelope_type", type);
        node.put("run_id", "run-1");
        node.put("robot_id", "robot-17");
        node.putNull("topic");
        node.put("stream_timestamp_ms", timestamp);
        return node;
    }

    private static final class Harness implements AutoCloseable {
        private final KeyedOneInputStreamOperatorTestHarness<String, JsonNode, String> delegate;

        private Harness(
                KeyedOneInputStreamOperatorTestHarness<String, JsonNode, String> delegate) {
            this.delegate = delegate;
        }

        void process(JsonNode value) throws Exception {
            delegate.processElement(new StreamRecord<>(value));
        }

        void processingTime(long timestamp) throws Exception {
            delegate.setProcessingTime(timestamp);
        }

        void watermark(long timestamp) throws Exception {
            delegate.processWatermark(new Watermark(timestamp));
        }

        List<JsonNode> metrics() {
            return delegate.extractOutputValues().stream()
                    .map(RobotLivenessProcessorHarnessTest::read)
                    .toList();
        }

        List<JsonNode> anomalies() {
            var records = delegate.getSideOutput(RobotLivenessProcessor.ANOMALIES);
            if (records == null) return List.of();
            return records.stream()
                    .map(StreamRecord::getValue)
                    .map(RobotLivenessProcessorHarnessTest::read)
                    .toList();
        }

        @Override
        public void close() throws Exception {
            delegate.close();
        }
    }

    private static JsonNode read(String value) {
        try {
            return JsonSupport.MAPPER.readTree(value);
        } catch (Exception exception) {
            throw new IllegalArgumentException(exception);
        }
    }
}
