package io.github.mikehstudio.rostelemetry;

import com.fasterxml.jackson.databind.JsonNode;
import java.nio.charset.StandardCharsets;
import org.apache.flink.connector.kafka.sink.KafkaRecordSerializationSchema;
import org.apache.kafka.clients.producer.ProducerRecord;

/** Keeps all revisions of a logical entity on the same Kafka partition. */
final class JsonKeyedSerializationSchema implements KafkaRecordSerializationSchema<String> {
    private final String topic;
    private final String kind;

    JsonKeyedSerializationSchema(String topic, String kind) {
        this.topic = topic;
        this.kind = kind;
    }

    @Override
    public ProducerRecord<byte[], byte[]> serialize(
            String element, KafkaSinkContext context, Long timestamp) {
        try {
            JsonNode node = JsonSupport.MAPPER.readTree(element);
            String key = switch (kind) {
                case "metric" -> String.join("|",
                        node.path("run_id").asText(), node.path("robot_id").asText(),
                        node.path("topic").asText("__robot__"), node.path("metric_type").asText(),
                        node.path("window_start_ms").asText("null"),
                        node.path("window_end_ms").asText("null"));
                case "anomaly" -> node.path("anomaly_id").asText();
                case "late" -> node.path("event_id").asText("unknown");
                default -> node.path("envelope_id").asText(
                        node.path("event_id").asText("dead-letter"));
            };
            return new ProducerRecord<>(
                    topic,
                    key.getBytes(StandardCharsets.UTF_8),
                    element.getBytes(StandardCharsets.UTF_8));
        } catch (Exception exception) {
            throw new IllegalArgumentException("Cannot serialize output record", exception);
        }
    }
}
