package io.github.mikehstudio.rostelemetry;

import com.fasterxml.jackson.databind.JsonNode;
import com.networknt.schema.InputFormat;
import com.networknt.schema.Schema;
import com.networknt.schema.SchemaLocation;
import com.networknt.schema.SchemaRegistry;
import com.networknt.schema.SpecificationVersion;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import org.apache.flink.streaming.api.functions.ProcessFunction;
import org.apache.flink.util.Collector;
import org.apache.flink.util.OutputTag;

final class ParseEnvelopeFunction extends ProcessFunction<String, JsonNode> {
    static final OutputTag<String> DEAD_LETTER = new OutputTag<>("dead-letter") {};
    private static final String SCHEMA_BASE =
            "https://github.com/mikeh-studio/ros-telemetry-analytics/schemas/";
    private static final Schema ENVELOPE_SCHEMA = loadSchema();

    @Override
    public void processElement(String value, Context context, Collector<JsonNode> output) {
        try {
            var errors = ENVELOPE_SCHEMA.validate(value, InputFormat.JSON);
            if (!errors.isEmpty()) {
                throw new IllegalArgumentException("Envelope failed v1 schema: " + errors.get(0));
            }
            JsonNode envelope = JsonSupport.MAPPER.readTree(value);
            output.collect(envelope);
        } catch (Exception exception) {
            ObjectNodeBuilder error = new ObjectNodeBuilder();
            error.put("error", exception.getMessage());
            error.put("raw_value", value);
            error.put("observed_at_ms", System.currentTimeMillis());
            context.output(DEAD_LETTER, error.write());
        }
    }

    private static Schema loadSchema() {
        Map<String, String> schemas = Map.of(
                SCHEMA_BASE + "telemetry-envelope-v1.schema.json",
                resource("telemetry-envelope-v1.schema.json"),
                SCHEMA_BASE + "telemetry-event-v1.schema.json",
                resource("telemetry-event-v1.schema.json"));
        SchemaRegistry registry = SchemaRegistry.withDefaultDialect(
                SpecificationVersion.DRAFT_2020_12,
                builder -> builder.schemas(schemas));
        return registry.getSchema(
                SchemaLocation.of(SCHEMA_BASE + "telemetry-envelope-v1.schema.json"));
    }

    private static String resource(String filename) {
        try (InputStream stream = ParseEnvelopeFunction.class.getResourceAsStream(
                "/schemas/" + filename)) {
            if (stream == null) throw new IllegalStateException("Missing schema resource: " + filename);
            return new String(stream.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException exception) {
            throw new IllegalStateException("Cannot load schema resource: " + filename, exception);
        }
    }

    private static final class ObjectNodeBuilder {
        private final com.fasterxml.jackson.databind.node.ObjectNode node = JsonSupport.object();

        void put(String name, String value) {
            node.put(name, value == null ? "unknown" : value);
        }

        void put(String name, long value) {
            node.put(name, value);
        }

        String write() {
            return JsonSupport.write(node);
        }
    }
}
