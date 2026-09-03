package io.github.mikehstudio.rostelemetry;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.List;
import org.apache.flink.api.common.typeinfo.Types;
import org.apache.flink.streaming.api.operators.KeyedProcessOperator;
import org.apache.flink.streaming.runtime.streamrecord.StreamRecord;
import org.apache.flink.streaming.util.KeyedOneInputStreamOperatorTestHarness;
import org.junit.jupiter.api.Test;

final class CoordinatorHarnessTest {
    private static final List<String> TOPICS =
            List.of("/camera/image_raw", "/imu/data", "/odom", "/diagnostics");

    @Test
    void runBecomesRunningOnlyAfterFourUniqueRegistrations() throws Exception {
        KeyedProcessOperator<String, JsonNode, String> operator =
                new KeyedProcessOperator<>(new RunCoordinator());
        try (KeyedOneInputStreamOperatorTestHarness<String, JsonNode, String> harness =
                new KeyedOneInputStreamOperatorTestHarness<>(
                        operator, ignored -> "run-1|robot-17", Types.STRING)) {
            harness.open();
            for (int index = 0; index < 3; index++) {
                harness.processElement(new StreamRecord<>(registration(TOPICS.get(index))));
            }
            harness.processElement(new StreamRecord<>(registration(TOPICS.get(0))));
            assertTrue(harness.extractOutputValues().isEmpty());
            harness.processElement(new StreamRecord<>(registration(TOPICS.get(3))));

            List<String> output = harness.extractOutputValues();
            assertEquals(1, output.size());
            JsonNode ready = JsonSupport.MAPPER.readTree(output.get(0));
            assertEquals("running", ready.path("payload").path("status").asText());
            assertEquals(1, ready.path("revision").asInt());
        }
    }

    @Test
    void summaryReadyRequiresFourUniqueTopicSummariesAndEmitsOnce() throws Exception {
        KeyedProcessOperator<String, String, String> operator =
                new KeyedProcessOperator<>(new SummaryCoordinator());
        try (KeyedOneInputStreamOperatorTestHarness<String, String, String> harness =
                new KeyedOneInputStreamOperatorTestHarness<>(
                        operator, ignored -> "run-1|robot-17", Types.STRING)) {
            harness.open();
            for (int index = 0; index < 3; index++) {
                harness.processElement(new StreamRecord<>(summary(TOPICS.get(index))));
            }
            harness.processElement(new StreamRecord<>(summary(TOPICS.get(0))));
            assertTrue(harness.extractOutputValues().isEmpty());
            harness.processElement(new StreamRecord<>(summary(TOPICS.get(3))));
            harness.processElement(new StreamRecord<>(summary(TOPICS.get(3))));

            List<String> output = harness.extractOutputValues();
            assertEquals(1, output.size());
            JsonNode ready = JsonSupport.MAPPER.readTree(output.get(0));
            assertEquals("summary_ready", ready.path("payload").path("status").asText());
            assertEquals(4, ready.path("payload").path("summary_topic_count").asInt());
        }
    }

    @Test
    void coordinatorsHonorTheDatasetTopicCountAndMetadata() throws Exception {
        KeyedProcessOperator<String, JsonNode, String> runOperator =
                new KeyedProcessOperator<>(new RunCoordinator());
        try (KeyedOneInputStreamOperatorTestHarness<String, JsonNode, String> harness =
                new KeyedOneInputStreamOperatorTestHarness<>(
                        runOperator, ignored -> "run-2|robot-17", Types.STRING)) {
            harness.open();
            harness.processElement(new StreamRecord<>(registration("/scan", 2)));
            assertTrue(harness.extractOutputValues().isEmpty());
            harness.processElement(new StreamRecord<>(registration("/odom", 2)));
            JsonNode ready = JsonSupport.MAPPER.readTree(harness.extractOutputValues().get(0));
            assertEquals(2, ready.path("payload").path("expected_topic_count").asInt());
            assertEquals("lilocbench_dynamics_0", ready.path("payload").path("dataset_id").asText());
        }

        KeyedProcessOperator<String, String, String> summaryOperator =
                new KeyedProcessOperator<>(new SummaryCoordinator());
        try (KeyedOneInputStreamOperatorTestHarness<String, String, String> harness =
                new KeyedOneInputStreamOperatorTestHarness<>(
                        summaryOperator, ignored -> "run-2|robot-17", Types.STRING)) {
            harness.open();
            harness.processElement(new StreamRecord<>(summary("/scan", 2)));
            assertTrue(harness.extractOutputValues().isEmpty());
            harness.processElement(new StreamRecord<>(summary("/odom", 2)));
            JsonNode ready = JsonSupport.MAPPER.readTree(harness.extractOutputValues().get(0));
            assertEquals(2, ready.path("payload").path("summary_topic_count").asInt());
            assertEquals("lilocbench_dynamics_0", ready.path("payload").path("dataset_id").asText());
        }
    }

    private static JsonNode registration(String topic) {
        ObjectNode node = base(topic);
        node.put("envelope_type", "topic_registered");
        return node;
    }

    private static JsonNode registration(String topic, int expectedTopicCount) {
        ObjectNode node = (ObjectNode) registration(topic);
        ObjectNode body = node.putObject("body");
        body.put("expected_topic_count", expectedTopicCount);
        body.put("dataset_id", "lilocbench_dynamics_0");
        return node;
    }

    private static String summary(String topic) {
        ObjectNode node = base(topic);
        node.put("metric_id", JsonSupport.sha256(topic));
        node.put("metric_type", "mission_summary");
        node.put("revision", 0);
        node.putObject("payload").put("status", "ok");
        return JsonSupport.write(node);
    }

    private static String summary(String topic, int expectedTopicCount) {
        ObjectNode node = base(topic);
        node.put("metric_id", JsonSupport.sha256(topic));
        node.put("metric_type", "mission_summary");
        node.put("revision", 0);
        ObjectNode payload = node.putObject("payload");
        payload.put("status", "ok");
        payload.put("expected_topic_count", expectedTopicCount);
        payload.put("dataset_id", "lilocbench_dynamics_0");
        return JsonSupport.write(node);
    }

    private static ObjectNode base(String topic) {
        ObjectNode node = JsonSupport.object();
        node.put("schema_version", 1);
        node.put("run_id", "run-1");
        node.put("robot_id", "robot-17");
        node.put("topic", topic);
        node.put("stream_timestamp_ms", 90_000);
        return node;
    }
}
