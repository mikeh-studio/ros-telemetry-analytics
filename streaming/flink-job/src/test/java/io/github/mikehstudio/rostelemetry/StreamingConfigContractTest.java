package io.github.mikehstudio.rostelemetry;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.apache.flink.api.common.state.StateTtlConfig;
import org.junit.jupiter.api.Test;
import org.yaml.snakeyaml.Yaml;

final class StreamingConfigContractTest {
    private static final Path CONFIG = Path.of("..", "..", "configs", "streaming_demo.yaml");

    @Test
    @SuppressWarnings("unchecked")
    void javaRuntimeDefaultsMatchTheSharedStreamingSpecification() throws Exception {
        Map<String, Object> root;
        try (InputStream stream = Files.newInputStream(CONFIG)) {
            root = new Yaml().load(stream);
        }
        Map<String, Object> analytics = (Map<String, Object>) root.get("analytics");
        Map<String, Object> flink = (Map<String, Object>) root.get("flink");
        List<Map<String, Object>> topics =
                (List<Map<String, Object>>) analytics.get("expected_topics");

        assertEquals(asLong(analytics, "window_size_ms"), StreamingDefaults.WINDOW_MS);
        assertEquals(asLong(analytics, "window_slide_ms"), StreamingDefaults.SLIDE_MS);
        assertEquals(asLong(analytics, "recovery_gate_ms"), StreamingDefaults.RECOVERY_GATE_MS);
        assertEquals(
                asLong(analytics, "maximum_out_of_orderness_ms"),
                StreamingDefaults.MAXIMUM_OUT_OF_ORDERNESS_MS);
        assertEquals(
                asLong(analytics, "allowed_lateness_ms"),
                StreamingDefaults.ALLOWED_LATENESS_MS);
        assertEquals(
                asLong(analytics, "idle_partition_timeout_ms"),
                StreamingDefaults.IDLE_PARTITION_TIMEOUT_MS);
        assertEquals(
                asLong(analytics, "whole_robot_silence_ms"),
                StreamingDefaults.WHOLE_ROBOT_SILENCE_MS);
        assertEquals(
                asDouble(analytics, "minimum_rate_ratio"),
                StreamingDefaults.MINIMUM_RATE_RATIO);
        assertEquals(
                asDouble(analytics, "maximum_rate_ratio"),
                StreamingDefaults.MAXIMUM_RATE_RATIO);
        assertEquals(
                asDouble(analytics, "gap_threshold_multiplier"),
                StreamingDefaults.GAP_THRESHOLD_MULTIPLIER);
        assertEquals(topics.size(), StreamingDefaults.EXPECTED_TOPIC_COUNT);

        assertEquals(
                asLong(flink, "state_ttl_minutes"), StreamingDefaults.STATE_TTL_MINUTES);
        assertEquals(
                asLong(flink, "checkpoint_interval_ms"),
                StreamingDefaults.CHECKPOINT_INTERVAL_MS);
        assertEquals(
                asLong(flink, "checkpoint_min_pause_ms"),
                StreamingDefaults.CHECKPOINT_MIN_PAUSE_MS);
        assertEquals(
                asLong(flink, "checkpoint_timeout_ms"),
                StreamingDefaults.CHECKPOINT_TIMEOUT_MS);
        assertEquals(asLong(flink, "restart_attempts"), StreamingDefaults.RESTART_ATTEMPTS);
        assertEquals(asLong(flink, "restart_delay_ms"), StreamingDefaults.RESTART_DELAY_MS);
        assertEquals(
                asLong(flink, "kafka_transaction_timeout_ms"),
                StreamingDefaults.KAFKA_TRANSACTION_TIMEOUT_MS);

        StateTtlConfig ttl = StreamingDefaults.stateTtl();
        assertEquals(
                StateTtlConfig.UpdateType.OnCreateAndWrite,
                ttl.getUpdateType());
        assertEquals(
                StateTtlConfig.StateVisibility.NeverReturnExpired,
                ttl.getStateVisibility());
        assertEquals(
                StreamingDefaults.STATE_TTL_MINUTES,
                ttl.getTimeToLive().toMinutes());
    }

    private static long asLong(Map<String, Object> values, String key) {
        return ((Number) values.get(key)).longValue();
    }

    private static double asDouble(Map<String, Object> values, String key) {
        return ((Number) values.get(key)).doubleValue();
    }
}
