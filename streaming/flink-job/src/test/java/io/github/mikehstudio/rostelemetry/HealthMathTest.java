package io.github.mikehstudio.rostelemetry;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import com.fasterxml.jackson.databind.JsonNode;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;
import org.junit.jupiter.api.Named;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

class HealthMathTest {
    private static final Path CASES =
            Path.of("..", "..", "configs", "health_math_contract_cases.json");

    @ParameterizedTest(name = "{0}")
    @MethodSource("contractCases")
    void matchesTheSharedPythonJavaFormulaContract(
            String ignored, JsonNode contract, JsonNode testCase) {
        List<Long> timestamps = new ArrayList<>();
        testCase.path("timestamps_ns").forEach(value -> timestamps.add(value.asLong()));
        HealthMath.Summary actual = HealthMath.summarize(
                timestamps,
                testCase.path("expected_rate_hz").asDouble(),
                contract.path("gap_threshold_multiplier").asDouble(),
                contract.path("minimum_rate_ratio").asDouble(),
                contract.path("maximum_rate_ratio").asDouble(),
                1_000_000_000L);
        JsonNode expected = testCase.path("expected");

        assertEquals(expected.path("message_count").asLong(), actual.messageCount());
        assertNullableLong(expected.path("first_timestamp_ns"), actual.firstTimestampMs());
        assertNullableLong(expected.path("last_timestamp_ns"), actual.lastTimestampMs());
        assertNullableDouble(expected.path("duration_s"), actual.durationSeconds());
        assertNullableDouble(expected.path("mean_rate_hz"), actual.meanRateHz());
        assertNullableDouble(expected.path("rate_ratio"), actual.rateRatio());
        assertNullableDouble(
                expected.path("max_inter_message_gap_s"), actual.maxGapSeconds());
        assertNullableDouble(
                expected.path("p95_inter_message_gap_s"), actual.p95GapSeconds());
        assertEquals(expected.path("gap_event_count").asLong(), actual.gapEventCount());
        assertEquals(
                expected.path("estimated_dropped_messages").asLong(),
                actual.estimatedDroppedMessages());
        assertEquals(expected.path("status").asText(), actual.status());
    }

    private static Stream<Arguments> contractCases() throws Exception {
        JsonNode root = JsonSupport.MAPPER.readTree(Files.readString(CASES));
        List<Arguments> arguments = new ArrayList<>();
        root.path("cases").forEach(testCase -> arguments.add(Arguments.of(
                Named.of(testCase.path("name").asText(), testCase.path("name").asText()),
                root,
                testCase)));
        return arguments.stream();
    }

    private static void assertNullableLong(JsonNode expected, Long actual) {
        if (expected.isNull()) assertNull(actual);
        else assertEquals(expected.asLong(), actual);
    }

    private static void assertNullableDouble(JsonNode expected, Double actual) {
        if (expected.isNull()) assertNull(actual);
        else assertEquals(expected.asDouble(), actual, 1e-12);
    }
}
