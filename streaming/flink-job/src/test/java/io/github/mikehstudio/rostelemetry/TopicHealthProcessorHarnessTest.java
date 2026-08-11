package io.github.mikehstudio.rostelemetry;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.List;
import org.apache.flink.api.common.typeinfo.Types;
import org.apache.flink.streaming.api.operators.KeyedProcessOperator;
import org.apache.flink.streaming.api.watermark.Watermark;
import org.apache.flink.streaming.util.KeyedOneInputStreamOperatorTestHarness;
import org.apache.flink.streaming.runtime.streamrecord.StreamRecord;
import org.junit.jupiter.api.Test;

final class TopicHealthProcessorHarnessTest {
    private static final String RUN = "run-1";
    private static final String ROBOT = "robot-17";
    private static final String TOPIC = "/camera/image_raw";

    @Test
    void opensNeverSeenFromTheRealEventTimeTimerOnlyOnce() throws Exception {
        try (Harness harness = harness()) {
            harness.process(registration(100_000, 30.0, 2_000, 5_000));
            harness.watermark(102_000);
            harness.watermark(104_000);

            List<JsonNode> anomalies = harness.sideValues(TopicHealthProcessor.ANOMALIES);
            assertEquals(1, anomalies.size());
            assertEquals("NEVER_SEEN", anomalies.get(0).path("condition_type").asText());
            assertEquals("active", anomalies.get(0).path("status").asText());
            assertEquals("error", anomalies.get(0).path("severity").asText());
        }
    }

    @Test
    void gapRecoversOnlyAfterTheOneSecondDensityGate() throws Exception {
        try (Harness harness = harness()) {
            harness.process(registration(100_000, 30.0, 2_000, 5_000));
            harness.process(telemetry("first", 100_000, 0, 1_000_000_000L));
            harness.watermark(105_000);

            List<JsonNode> active = harness.sideValues(TopicHealthProcessor.ANOMALIES);
            assertEquals(1, active.size());
            assertEquals("GAP", active.get(0).path("condition_type").asText());
            assertEquals(4_000, active.get(0).path("evidence").path("incident_duration_ms").asLong());
            String anomalyId = active.get(0).path("anomaly_id").asText();
            assertEquals(
                    JsonSupport.sha256(RUN, ROBOT, TOPIC, "GAP", 105_000),
                    anomalyId);

            for (int index = 0; index < 25; index++) {
                long timestamp = 105_100 + index * 40L;
                harness.process(telemetry(
                        "recovery-" + index,
                        timestamp,
                        index + 1L,
                        2_000_000_000L + index * 40_000_000L));
            }
            harness.watermark(106_100);

            List<JsonNode> transitions = harness.sideValues(TopicHealthProcessor.ANOMALIES);
            assertEquals(2, transitions.size());
            JsonNode recovered = transitions.get(1);
            assertEquals(anomalyId, recovered.path("anomaly_id").asText());
            assertEquals("recovered", recovered.path("status").asText());
            assertEquals(1, recovered.path("revision").asInt());
            assertEquals(25, recovered.path("evidence").path("recovery_event_count").asInt());
            assertEquals(5_100, recovered.path("evidence").path("incident_duration_ms").asLong());
            assertEquals(
                    1_000_000_000L,
                    recovered.path("evidence").path("last_on_time_source_timestamp_ns").asLong());
        }
    }

    @Test
    void acceptedLateRevisesClosedWindowsWhileDuplicateAndTooLateUseSideOutput()
            throws Exception {
        try (Harness harness = harness()) {
            harness.process(registration(100_000, 1.0, 2_000, 5_000));
            harness.process(telemetry("on-time", 100_000, 0, 1_000_000_000L));
            harness.watermark(112_000);

            List<JsonNode> initial = harness.mainValues("topic_window");
            JsonNode original = initial.stream()
                    .filter(node -> node.path("window_end_ms").asLong() == 110_000)
                    .findFirst()
                    .orElseThrow();
            assertEquals(0, original.path("revision").asInt());

            ObjectNode acceptedLate = telemetry("accepted-late", 109_000, 1, 10_000_000_000L);
            harness.process(acceptedLate);
            List<JsonNode> revised = harness.mainValues("topic_window");
            JsonNode correction = revised.stream()
                    .filter(node -> node.path("window_end_ms").asLong() == 110_000)
                    .filter(node -> node.path("revision").asInt() == 1)
                    .findFirst()
                    .orElseThrow();
            assertNotEquals(
                    original.path("metric_id").asText(), correction.path("metric_id").asText());
            assertEquals(1, correction.path("payload").path("accepted_late_count").asInt());

            harness.process(acceptedLate);
            harness.process(telemetry("too-late", 106_999, 2, 8_000_000_000L));
            List<JsonNode> rejected = harness.sideValues(TopicHealthProcessor.LATE_EVENTS);
            assertEquals(2, rejected.size());
            assertEquals("duplicate", rejected.get(0).path("reason").asText());
            assertEquals("beyond_allowed_lateness", rejected.get(1).path("reason").asText());
        }
    }

    @Test
    void rateConditionUsesTwoBadAndTwoHealthyFullWindowsWithoutRepeatedActiveEvents()
            throws Exception {
        try (Harness harness = harness()) {
            harness.process(registration(0, 1.0, 2_000, 100_000));
            harness.process(telemetry("first", 0, 0, 0));
            harness.watermark(10_000);
            assertTrue(harness.sideValues(TopicHealthProcessor.ANOMALIES).isEmpty());
            harness.watermark(11_000);

            List<JsonNode> active = harness.sideValues(TopicHealthProcessor.ANOMALIES);
            assertEquals(1, active.size());
            assertEquals("RATE", active.get(0).path("condition_type").asText());
            assertEquals("active", active.get(0).path("status").asText());
            String anomalyId = active.get(0).path("anomaly_id").asText();

            for (int index = 0; index < 11; index++) {
                long timestamp = 11_100 + index * 1_000L;
                harness.process(telemetry(
                        "healthy-" + index,
                        timestamp,
                        index + 1L,
                        (index + 1L) * 1_000_000_000L));
                harness.watermark(timestamp);
            }

            List<JsonNode> transitions = harness.sideValues(TopicHealthProcessor.ANOMALIES);
            assertEquals(2, transitions.size());
            assertEquals(anomalyId, transitions.get(1).path("anomaly_id").asText());
            assertEquals("recovered", transitions.get(1).path("status").asText());
            assertEquals(1, transitions.get(1).path("revision").asInt());
        }
    }

    @Test
    void endEmitsEightyOneFullWindowsNinePartialsAndOneSummary() throws Exception {
        try (Harness harness = harness()) {
            harness.process(registration(0, 1.0, 2_000, 5_000));
            assertEquals(2, harness.eventTimeTimers());
            for (int second = 0; second < 90; second++) {
                harness.process(telemetry(
                        "event-" + second,
                        second * 1_000L,
                        second,
                        second * 1_000_000_000L));
                harness.watermark(second * 1_000L);
                if (second == 10) {
                    assertEquals(1, harness.mainValues("topic_window").size());
                }
            }
            harness.process(lifecycle("run_ended", 90_000));
            harness.watermark(90_000);
            harness.watermark(97_000);

            List<JsonNode> windows = harness.mainValues("topic_window");
            assertEquals(90, windows.size());
            assertEquals(
                    81,
                    windows.stream()
                            .filter(node -> node.path("payload").path("window_status")
                                    .asText().equals("complete"))
                            .count());
            assertEquals(
                    9,
                    windows.stream()
                            .filter(node -> node.path("payload").path("window_status")
                                    .asText().equals("partial"))
                            .count());
            List<JsonNode> summaries = harness.mainValues("mission_summary");
            assertEquals(1, summaries.size());
            assertEquals(90, summaries.get(0).path("payload").path("message_count").asInt());
            assertEquals(0, harness.keyedStateEntries());
        }
    }

    @Test
    void pauseCancelsAnalyticalTimersAndAbortNeverEmitsASummary() throws Exception {
        try (Harness paused = harness()) {
            paused.process(registration(0, 1.0, 2_000, 5_000));
            paused.process(telemetry("event", 0, 0, 0));
            assertEquals(3, paused.eventTimeTimers());
            paused.process(lifecycle("run_paused", 0));
            assertEquals(0, paused.eventTimeTimers());
            paused.watermark(20_000);
            assertTrue(paused.mainValues(null).isEmpty());
            assertTrue(paused.sideValues(TopicHealthProcessor.ANOMALIES).isEmpty());
            paused.process(lifecycle("run_resumed", 0));
            assertEquals(2, paused.eventTimeTimers());
        }
        try (Harness aborted = harness()) {
            aborted.process(registration(0, 1.0, 2_000, 5_000));
            aborted.process(telemetry("event", 0, 0, 0));
            aborted.process(lifecycle("run_aborted", 1_000));
            assertEquals(0, aborted.eventTimeTimers());
            aborted.watermark(100_000);
            assertTrue(aborted.mainValues("mission_summary").isEmpty());
            assertEquals(0, aborted.keyedStateEntries());
        }
        try (Harness failed = harness()) {
            failed.process(registration(0, 1.0, 2_000, 5_000));
            failed.process(telemetry("event", 0, 0, 0));
            failed.process(lifecycle("run_failed", 1_000));
            assertEquals(0, failed.eventTimeTimers());
            failed.watermark(100_000);
            assertTrue(failed.mainValues("mission_summary").isEmpty());
            assertEquals(0, failed.keyedStateEntries());
        }
    }

    @Test
    void replacingGapTimerDeletesThePreviousRegistration() throws Exception {
        try (Harness harness = harness()) {
            harness.process(registration(0, 1.0, 2_000, 5_000));
            harness.process(telemetry("first", 0, 0, 0));
            assertEquals(3, harness.eventTimeTimers());

            harness.process(telemetry("second", 1_000, 1, 1_000_000_000L));

            assertEquals(3, harness.eventTimeTimers());
            harness.watermark(5_000);
            assertTrue(harness.sideValues(TopicHealthProcessor.ANOMALIES).isEmpty());
            harness.watermark(6_000);
            assertEquals(
                    "GAP",
                    harness.sideValues(TopicHealthProcessor.ANOMALIES).get(0)
                            .path("condition_type")
                            .asText());
        }
    }

    @Test
    void runEndedFreezesRateHistoryWhileFinalWindowsAndSummaryFinish() throws Exception {
        try (Harness harness = harness()) {
            harness.process(registration(0, 1.0, 2_000, 100_000));
            harness.process(telemetry("first", 0, 0, 0));
            harness.process(lifecycle("run_ended", 90_000));

            harness.watermark(11_000);
            assertTrue(harness.sideValues(TopicHealthProcessor.ANOMALIES).isEmpty());
            harness.watermark(95_000);

            assertEquals(1, harness.mainValues("mission_summary").size());
            assertTrue(harness.sideValues(TopicHealthProcessor.ANOMALIES).isEmpty());
        }
    }

    @Test
    void exactCameraDropoutTimelineProducesOneRecoveredGapAndBoundedWindowRevisions()
            throws Exception {
        try (Harness harness = harness()) {
            harness.process(registration(0, 30.0, 2_000, 5_000));
            List<ObjectNode> resumed = new java.util.ArrayList<>();
            ObjectNode heldAt61 = null;
            ObjectNode heldAt62 = null;
            for (int index = 0; index < 2_700; index++) {
                long offset = Math.round(index * 1_000.0 / 30.0);
                ObjectNode event = telemetry(
                        "camera-" + index,
                        offset,
                        index,
                        offset * 1_000_000L);
                if (offset <= 60_000) harness.process(event);
                else if (offset == 61_000) heldAt61 = event;
                else if (offset == 62_000) heldAt62 = event;
                else if (offset >= 68_000) resumed.add(event);
            }

            harness.watermark(65_001);
            harness.process(heldAt61);
            harness.process(heldAt62);
            for (ObjectNode event : resumed) harness.process(event);
            harness.watermark(69_001);
            harness.process(lifecycle("run_ended", 90_000));
            harness.watermark(97_000);

            List<JsonNode> incidents = harness.sideValues(TopicHealthProcessor.ANOMALIES);
            assertEquals(2, incidents.size());
            assertEquals(List.of("GAP", "GAP"), incidents.stream()
                    .map(node -> node.path("condition_type").asText())
                    .toList(), incidents.toString());
            assertEquals(List.of("active", "recovered"), incidents.stream()
                    .map(node -> node.path("status").asText())
                    .toList());
            assertEquals(30, incidents.get(1).path("evidence")
                    .path("recovery_event_count").asInt());

            List<JsonNode> windows = harness.mainValues("topic_window");
            JsonNode preGapWindow = windows.stream()
                    .filter(node -> node.path("window_end_ms").asLong() == 64_000)
                    .filter(node -> node.path("revision").asInt() == 0)
                    .findFirst()
                    .orElseThrow();
            assertEquals(
                    "GAP",
                    preGapWindow.path("payload")
                            .path("health_transition_suppressed_by")
                            .asText());
            assertEquals(81, windows.stream()
                    .filter(node -> node.path("revision").asInt() == 0)
                    .filter(node -> node.path("payload").path("window_status")
                            .asText().equals("complete"))
                    .count());
            assertTrue(windows.stream()
                    .filter(node -> node.path("revision").asInt() > 0)
                    .count() <= 20);
            assertEquals(9, windows.stream()
                    .filter(node -> node.path("payload").path("window_status")
                            .asText().equals("partial"))
                    .count());

            JsonNode summary = harness.mainValues("mission_summary").get(0);
            assertEquals(2, summary.path("payload").path("accepted_late_count").asInt());
            assertEquals("warn", summary.path("payload").path("status").asText());
            assertEquals(0, harness.keyedStateEntries());
        }
    }

    private static Harness harness() throws Exception {
        TimerAwareOperator operator = new TimerAwareOperator(new TopicHealthProcessor());
        KeyedOneInputStreamOperatorTestHarness<String, JsonNode, String> delegate =
                new KeyedOneInputStreamOperatorTestHarness<>(
                        operator,
                        node -> node.path("run_id").asText()
                                + "|"
                                + node.path("robot_id").asText()
                                + "|"
                                + node.path("topic").asText(),
                        Types.STRING);
        delegate.open();
        return new Harness(delegate, operator);
    }

    private static ObjectNode registration(
            long streamStart, double expectedRate, long startupGrace, long dropoutThreshold) {
        ObjectNode node = base("topic_registered", streamStart);
        node.put("event_timestamp_ns", 0);
        ObjectNode body = node.putObject("body");
        body.put("expected_rate_hz", expectedRate);
        body.put("startup_grace_ms", startupGrace);
        body.put("dropout_threshold_ms", dropoutThreshold);
        return node;
    }

    private static ObjectNode telemetry(
            String eventId, long streamTimestamp, long sequence, long sourceTimestampNs) {
        ObjectNode node = base("telemetry", streamTimestamp);
        ObjectNode body = node.putObject("body");
        body.put("event_id", eventId);
        body.put("event_timestamp_ns", sourceTimestampNs);
        body.put("sequence", sequence);
        return node;
    }

    private static ObjectNode lifecycle(String type, long streamTimestamp) {
        ObjectNode node = base(type, streamTimestamp);
        node.putObject("body").put("replay_rate", 1);
        return node;
    }

    private static ObjectNode base(String type, long streamTimestamp) {
        ObjectNode node = JsonSupport.object();
        node.put("schema_version", 1);
        node.put("envelope_id", JsonSupport.sha256(type, streamTimestamp));
        node.put("envelope_type", type);
        node.put("run_id", RUN);
        node.put("robot_id", ROBOT);
        node.put("topic", TOPIC);
        node.put("stream_timestamp_ms", streamTimestamp);
        return node;
    }

    private static final class Harness implements AutoCloseable {
        private final KeyedOneInputStreamOperatorTestHarness<String, JsonNode, String> delegate;
        private final TimerAwareOperator operator;

        private Harness(
                KeyedOneInputStreamOperatorTestHarness<String, JsonNode, String> delegate,
                TimerAwareOperator operator) {
            this.delegate = delegate;
            this.operator = operator;
        }

        void process(JsonNode node) throws Exception {
            delegate.processElement(new StreamRecord<>(node, node.path("stream_timestamp_ms").asLong()));
        }

        void watermark(long timestamp) throws Exception {
            operator.advanceEventTime(timestamp);
            delegate.processWatermark(timestamp);
        }

        List<JsonNode> mainValues(String metricType) {
            return delegate.extractOutputValues().stream()
                    .map(TopicHealthProcessorHarnessTest::read)
                    .filter(node -> metricType == null
                            || node.path("metric_type").asText().equals(metricType))
                    .toList();
        }

        List<JsonNode> sideValues(org.apache.flink.util.OutputTag<String> tag) {
            var records = delegate.getSideOutput(tag);
            if (records == null) return List.of();
            return records.stream()
                    .map(StreamRecord::getValue)
                    .map(TopicHealthProcessorHarnessTest::read)
                    .toList();
        }

        int keyedStateEntries() {
            return delegate.numKeyedStateEntries();
        }

        int eventTimeTimers() {
            return delegate.numEventTimeTimers();
        }

        @Override
        public void close() throws Exception {
            delegate.close();
        }
    }

    private static final class TimerAwareOperator
            extends KeyedProcessOperator<String, JsonNode, String> {
        private TimerAwareOperator(TopicHealthProcessor function) {
            super(function);
        }

        private void advanceEventTime(long timestamp) throws Exception {
            getTimeServiceManager().orElseThrow().advanceWatermark(new Watermark(timestamp));
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
