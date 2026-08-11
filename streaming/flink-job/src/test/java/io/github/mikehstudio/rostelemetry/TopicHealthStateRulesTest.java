package io.github.mikehstudio.rostelemetry;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

final class TopicHealthStateRulesTest {
    @Test
    void classifiesOnTimeAcceptedLateTooLateDuplicateAndStoppedRecords() {
        long watermark = 20_000;
        assertEquals(
                TopicHealthProcessor.TelemetryDisposition.ACCEPTED_ON_TIME,
                TopicHealthProcessor.classifyTelemetry(false, watermark, 20_000, true));
        assertEquals(
                TopicHealthProcessor.TelemetryDisposition.ACCEPTED_LATE,
                TopicHealthProcessor.classifyTelemetry(false, watermark, 18_000, true));
        assertEquals(
                TopicHealthProcessor.TelemetryDisposition.TOO_LATE,
                TopicHealthProcessor.classifyTelemetry(false, watermark, 14_999, true));
        assertEquals(
                TopicHealthProcessor.TelemetryDisposition.DUPLICATE,
                TopicHealthProcessor.classifyTelemetry(true, watermark, 14_000, true));
        assertEquals(
                TopicHealthProcessor.TelemetryDisposition.NOT_RUNNING,
                TopicHealthProcessor.classifyTelemetry(false, watermark, 20_000, false));
    }

    @Test
    void acceptsTheExactAllowedLatenessBoundary() {
        assertEquals(
                TopicHealthProcessor.TelemetryDisposition.ACCEPTED_LATE,
                TopicHealthProcessor.classifyTelemetry(false, 20_000, 15_000, true));
    }
}
