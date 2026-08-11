package io.github.mikehstudio.rostelemetry;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.apache.flink.streaming.api.operators.ProcessOperator;
import org.apache.flink.streaming.runtime.streamrecord.StreamRecord;
import org.apache.flink.streaming.util.OneInputStreamOperatorTestHarness;
import org.junit.jupiter.api.Test;

final class ParseEnvelopeFunctionHarnessTest {
    @Test
    void validatesTheFullEnvelopeSchemaAndRoutesMalformedRecords() throws Exception {
        ProcessOperator<String, JsonNode> operator =
                new ProcessOperator<>(new ParseEnvelopeFunction());
        try (OneInputStreamOperatorTestHarness<String, JsonNode> harness =
                new OneInputStreamOperatorTestHarness<>(operator)) {
            harness.open();
            ObjectNode valid = registration();
            harness.processElement(new StreamRecord<>(JsonSupport.write(valid)));
            assertEquals(1, harness.extractOutputValues().size());

            valid.put("unexpected", true);
            harness.processElement(new StreamRecord<>(JsonSupport.write(valid)));
            var rejected = harness.getSideOutput(ParseEnvelopeFunction.DEAD_LETTER);
            assertEquals(1, rejected.size());
            JsonNode error = JsonSupport.MAPPER.readTree(rejected.element().getValue());
            assertTrue(error.path("error").asText().contains("schema"));

            valid.remove("unexpected");
            valid.put("run_id", "../../outside");
            harness.processElement(new StreamRecord<>(JsonSupport.write(valid)));
            assertEquals(2, harness.getSideOutput(ParseEnvelopeFunction.DEAD_LETTER).size());
        }
    }

    private static ObjectNode registration() {
        ObjectNode node = JsonSupport.object();
        node.put("schema_version", 1);
        node.put("envelope_id", JsonSupport.sha256("registration"));
        node.put("envelope_type", "topic_registered");
        node.put("run_id", "run-1");
        node.put("robot_id", "robot-17");
        node.put("topic", "/odom");
        node.put("event_timestamp_ns", 1_000_000_000L);
        node.put("stream_timestamp_ms", 1_000L);
        node.put("ingest_timestamp_ms", 2_000L);
        ObjectNode body = node.putObject("body");
        body.put("message_type", "nav_msgs/msg/Odometry");
        body.put("expected_rate_hz", 20.0);
        body.put("startup_grace_ms", 2_000);
        body.put("dropout_threshold_ms", 2_000);
        return node;
    }
}
