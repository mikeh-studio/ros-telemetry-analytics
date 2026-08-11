package io.github.mikehstudio.rostelemetry;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.List;
import org.apache.flink.api.common.typeinfo.Types;
import org.apache.flink.streaming.api.operators.KeyedProcessOperator;
import org.apache.flink.streaming.runtime.streamrecord.StreamRecord;
import org.apache.flink.streaming.util.KeyedOneInputStreamOperatorTestHarness;
import org.junit.jupiter.api.Test;

final class RobotHealthProcessorHarnessTest {
    @Test
    void conditionsDriveHealthRecoveryAndPrimaryAnomalyPriority() throws Exception {
        KeyedProcessOperator<String, String, String> operator =
                new KeyedProcessOperator<>(new RobotHealthProcessor());
        try (KeyedOneInputStreamOperatorTestHarness<String, String, String> harness =
                new KeyedOneInputStreamOperatorTestHarness<>(
                        operator, ignored -> "run-1|robot-17", Types.STRING)) {
            harness.open();
            process(harness, healthSignal("healthy", 0));
            assertHealth(harness, "healthy", null, 0);

            process(harness, anomaly("rate", "RATE", "/camera/image_raw", "active", 10));
            assertHealth(harness, "degraded", "RATE", 1);
            process(harness, topicWindow("/camera/image_raw", true, 11));
            assertHealth(harness, "recovering", "RATE", 1);
            process(harness, topicWindow("/camera/image_raw", false, 12));

            process(harness, anomaly("gap", "GAP", "/camera/image_raw", "active", 20));
            assertHealth(harness, "degraded", "GAP", 2);
            process(harness, anomaly("never", "NEVER_SEEN", "/imu/data", "active", 30));
            assertHealth(harness, "degraded", "NEVER_SEEN", 3);
            process(harness, anomaly("offline", "ROBOT_OFFLINE", null, "active", 40));
            assertHealth(harness, "offline", "ROBOT_OFFLINE", 4);

            process(harness, anomaly("offline", "ROBOT_OFFLINE", null, "recovered", 50));
            assertHealth(harness, "degraded", "NEVER_SEEN", 3);
            process(harness, anomaly("never", "NEVER_SEEN", "/imu/data", "recovered", 60));
            process(harness, anomaly("gap", "GAP", "/camera/image_raw", "recovered", 70));
            process(harness, anomaly("rate", "RATE", "/camera/image_raw", "recovered", 80));
            assertHealth(harness, "healthy", null, 0);
        }
    }

    private static void assertHealth(
            KeyedOneInputStreamOperatorTestHarness<String, String, String> harness,
            String status,
            String primary,
            int count)
            throws Exception {
        List<String> output = harness.extractOutputValues();
        JsonNode metric = JsonSupport.MAPPER.readTree(output.get(output.size() - 1));
        JsonNode payload = metric.path("payload");
        assertEquals(status, payload.path("status").asText());
        assertEquals(count, payload.path("active_condition_count").asInt());
        if (primary == null) assertEquals(true, payload.path("primary_anomaly").isNull());
        else assertEquals(primary, payload.path("primary_anomaly").path("condition_type").asText());
    }

    private static void process(
            KeyedOneInputStreamOperatorTestHarness<String, String, String> harness,
            ObjectNode signal)
            throws Exception {
        harness.processElement(new StreamRecord<>(JsonSupport.write(signal)));
    }

    private static ObjectNode base(long timestamp) {
        ObjectNode node = JsonSupport.object();
        node.put("schema_version", 1);
        node.put("run_id", "run-1");
        node.put("robot_id", "robot-17");
        node.put("stream_timestamp_ms", timestamp);
        return node;
    }

    private static ObjectNode healthSignal(String status, long timestamp) {
        ObjectNode node = base(timestamp);
        node.put("metric_type", "robot_health");
        node.putObject("payload").put("status", status);
        return node;
    }

    private static ObjectNode topicWindow(String topic, boolean recovering, long timestamp) {
        ObjectNode node = base(timestamp);
        node.put("metric_type", "topic_window");
        node.put("topic", topic);
        node.putObject("payload").put("recovery_in_progress", recovering);
        return node;
    }

    private static ObjectNode anomaly(
            String id, String condition, String topic, String status, long timestamp) {
        ObjectNode node = base(timestamp);
        node.put("anomaly_id", id);
        node.put("condition_type", condition);
        if (topic == null) node.putNull("topic");
        else node.put("topic", topic);
        node.put("status", status);
        node.put("detected_stream_ms", timestamp);
        return node;
    }
}
