package io.github.mikehstudio.rostelemetry;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.node.ObjectNode;
import com.networknt.schema.InputFormat;
import com.networknt.schema.Schema;
import com.networknt.schema.SchemaRegistry;
import com.networknt.schema.SpecificationVersion;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

final class JsonSchemaContractTest {
    private static final Path SCHEMAS = Path.of("..", "..", "schemas");

    @Test
    void javaMetricRecordSatisfiesSharedMetricSchema() throws Exception {
        ObjectNode metric = metric();
        assertValid("telemetry-metric-v1.schema.json", metric);

        metric.put("revision", -1);
        assertInvalid("telemetry-metric-v1.schema.json", metric);
        metric.put("revision", 0);
        metric.put("unexpected", true);
        assertInvalid("telemetry-metric-v1.schema.json", metric);
    }

    @Test
    void javaAnomalyRecordSatisfiesSharedAnomalySchema() throws Exception {
        ObjectNode anomaly = anomaly();
        assertValid("telemetry-anomaly-v1.schema.json", anomaly);

        anomaly.put("severity", "critical");
        assertInvalid("telemetry-anomaly-v1.schema.json", anomaly);
        anomaly.put("severity", "warn");
        anomaly.remove("anomaly_id");
        assertInvalid("telemetry-anomaly-v1.schema.json", anomaly);
    }

    private static ObjectNode metric() {
        ObjectNode metric = JsonSupport.object();
        metric.put("schema_version", 1);
        metric.put("metric_id", JsonSupport.sha256(1, "run", "robot", "topic_window", 0));
        metric.put("metric_type", "topic_window");
        metric.put("run_id", "run-1");
        metric.put("robot_id", "robot-17");
        metric.put("topic", "/odom");
        metric.put("window_start_ms", 0);
        metric.put("window_end_ms", 10_000);
        metric.put("revision", 0);
        metric.put("stream_timestamp_ms", 10_000);
        metric.putObject("payload").put("status", "ok");
        return metric;
    }

    private static ObjectNode anomaly() {
        ObjectNode anomaly = JsonSupport.object();
        anomaly.put("schema_version", 1);
        anomaly.put("anomaly_id", JsonSupport.sha256(1, "run", "robot", "GAP", 10_000));
        anomaly.put("run_id", "run-1");
        anomaly.put("robot_id", "robot-17");
        anomaly.put("topic", "/camera/image_raw");
        anomaly.put("condition_type", "GAP");
        anomaly.put("status", "active");
        anomaly.put("severity", "warn");
        anomaly.put("revision", 0);
        anomaly.put("effective_start_stream_ms", 10_000);
        anomaly.put("detected_stream_ms", 10_000);
        anomaly.putNull("recovered_stream_ms");
        anomaly.putObject("evidence").put("silence_ms", 2_000);
        return anomaly;
    }

    private static Schema schema(String filename) throws Exception {
        String schemaData = Files.readString(SCHEMAS.resolve(filename));
        SchemaRegistry registry =
                SchemaRegistry.withDefaultDialect(SpecificationVersion.DRAFT_2020_12);
        return registry.getSchema(schemaData, InputFormat.JSON);
    }

    private static void assertValid(String filename, ObjectNode record) throws Exception {
        assertTrue(
                schema(filename).validate(JsonSupport.write(record), InputFormat.JSON).isEmpty(),
                () -> "Expected valid " + filename + ": " + record);
    }

    private static void assertInvalid(String filename, ObjectNode record) throws Exception {
        assertFalse(
                schema(filename).validate(JsonSupport.write(record), InputFormat.JSON).isEmpty(),
                () -> "Expected invalid " + filename + ": " + record);
    }
}
