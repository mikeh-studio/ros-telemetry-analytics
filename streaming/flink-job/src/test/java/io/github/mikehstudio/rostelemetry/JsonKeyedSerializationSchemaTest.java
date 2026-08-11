package io.github.mikehstudio.rostelemetry;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;

import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.junit.jupiter.api.Test;

final class JsonKeyedSerializationSchemaTest {
    @Test
    void metricRevisionsShareOneKafkaKeyWhileTheirValuesRemainDistinct() {
        JsonKeyedSerializationSchema schema =
                new JsonKeyedSerializationSchema("telemetry.metrics.v1", "metric");
        String original = metric(0);
        String correction = metric(1);
        ProducerRecord<byte[], byte[]> first = schema.serialize(original, null, null);
        ProducerRecord<byte[], byte[]> second = schema.serialize(correction, null, null);

        assertArrayEquals(first.key(), second.key());
        assertNotEquals(
                new String(first.value(), StandardCharsets.UTF_8),
                new String(second.value(), StandardCharsets.UTF_8));
    }

    private static String metric(int revision) {
        ObjectNode node = JsonSupport.object();
        node.put("schema_version", 1);
        node.put("metric_id", JsonSupport.sha256("metric", revision));
        node.put("metric_type", "topic_window");
        node.put("run_id", "run-1");
        node.put("robot_id", "robot-17");
        node.put("topic", "/odom");
        node.put("window_start_ms", 0);
        node.put("window_end_ms", 10_000);
        node.put("revision", revision);
        node.put("stream_timestamp_ms", 10_000);
        node.putObject("payload").put("status", "ok");
        return JsonSupport.write(node);
    }
}
