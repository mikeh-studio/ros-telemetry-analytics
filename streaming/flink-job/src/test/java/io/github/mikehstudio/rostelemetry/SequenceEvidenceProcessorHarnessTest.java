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

final class SequenceEvidenceProcessorHarnessTest {
    @Test
    void recordsGlobalGapsAndRegressionsButIgnoresDuplicateDelivery() throws Exception {
        KeyedProcessOperator<String, JsonNode, String> operator =
                new KeyedProcessOperator<>(new SequenceEvidenceProcessor());
        try (KeyedOneInputStreamOperatorTestHarness<String, JsonNode, String> harness =
                new KeyedOneInputStreamOperatorTestHarness<>(
                        operator, ignored -> "run-1|robot-17", Types.STRING)) {
            harness.open();
            harness.processElement(new StreamRecord<>(telemetry("event-1", 1)));
            harness.processElement(new StreamRecord<>(telemetry("event-3", 3)));
            harness.processElement(new StreamRecord<>(telemetry("event-2", 2)));
            harness.processElement(new StreamRecord<>(telemetry("event-3", 3)));

            List<String> output = harness.extractOutputValues();
            assertEquals(2, output.size());
            JsonNode gap = JsonSupport.MAPPER.readTree(output.get(0));
            JsonNode regression = JsonSupport.MAPPER.readTree(output.get(1));
            assertEquals("sequence_gap", gap.path("reason").asText());
            assertEquals(2, gap.path("expected_next_sequence").asLong());
            assertEquals(3, gap.path("observed_sequence").asLong());
            assertEquals("sequence_regression", regression.path("reason").asText());
            assertEquals(4, regression.path("expected_next_sequence").asLong());
            assertEquals(2, regression.path("observed_sequence").asLong());
        }
    }

    private static JsonNode telemetry(String eventId, long sequence) {
        ObjectNode node = JsonSupport.object();
        node.put("schema_version", 1);
        node.put("envelope_type", "telemetry");
        node.put("run_id", "run-1");
        node.put("robot_id", "robot-17");
        node.put("topic", "/camera/image_raw");
        node.put("stream_timestamp_ms", sequence * 10L);
        ObjectNode body = node.putObject("body");
        body.put("event_id", eventId);
        body.put("sequence", sequence);
        return node;
    }
}
