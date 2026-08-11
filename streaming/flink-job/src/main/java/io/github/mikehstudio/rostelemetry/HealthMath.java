package io.github.mikehstudio.rostelemetry;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class HealthMath {
    private HealthMath() {}

    public record Summary(
            long messageCount,
            Long firstTimestampMs,
            Long lastTimestampMs,
            Double durationSeconds,
            Double meanRateHz,
            double expectedRateHz,
            Double rateRatio,
            Double maxGapSeconds,
            Double p95GapSeconds,
            double gapThresholdSeconds,
            long gapEventCount,
            long estimatedDroppedMessages,
            String status) {}

    public static Summary summarize(
            List<Long> input,
            double expectedRateHz,
            double gapThresholdMultiplier,
            double minimumRateRatio,
            double maximumRateRatio) {
        return summarize(
                input,
                expectedRateHz,
                gapThresholdMultiplier,
                minimumRateRatio,
                maximumRateRatio,
                1_000L);
    }

    public static Summary summarize(
            List<Long> input,
            double expectedRateHz,
            double gapThresholdMultiplier,
            double minimumRateRatio,
            double maximumRateRatio,
            long unitsPerSecond) {
        if (input.isEmpty()) {
            return new Summary(
                    0,
                    null,
                    null,
                    null,
                    null,
                    expectedRateHz,
                    0.0,
                    null,
                    null,
                    gapThresholdMultiplier / expectedRateHz,
                    0,
                    0,
                    "error");
        }

        List<Long> timestamps = new ArrayList<>(input);
        Collections.sort(timestamps);
        long first = timestamps.get(0);
        long last = timestamps.get(timestamps.size() - 1);
        long durationMs = last - first;
        double durationSeconds = durationMs / (double) unitsPerSecond;
        List<Long> gaps = new ArrayList<>();
        for (int index = 1; index < timestamps.size(); index++) {
            gaps.add(timestamps.get(index) - timestamps.get(index - 1));
        }
        Double meanRate =
                timestamps.size() > 1 && durationMs > 0
                        ? (timestamps.size() - 1) * (double) unitsPerSecond / durationMs
                        : null;
        Double ratio = meanRate == null ? null : meanRate / expectedRateHz;
        double thresholdSeconds = gapThresholdMultiplier / expectedRateHz;
        double thresholdMs = thresholdSeconds * unitsPerSecond;
        long gapEvents = gaps.stream().filter(gap -> gap > thresholdMs).count();
        long estimatedDrops =
                durationMs > 0
                        ? Math.max(
                                0,
                                (long) Math.rint(durationSeconds * expectedRateHz)
                                        + 1
                                        - timestamps.size())
                        : 0;
        String status;
        if (timestamps.size() > 1 && durationMs == 0) {
            status = "error";
        } else if (timestamps.size() == 1) {
            status = "warn";
        } else if (gapEvents > 0
                || (ratio != null && (ratio < minimumRateRatio || ratio > maximumRateRatio))) {
            status = "warn";
        } else {
            status = "ok";
        }
        return new Summary(
                timestamps.size(),
                first,
                last,
                durationSeconds,
                meanRate,
                expectedRateHz,
                ratio,
                gaps.isEmpty() ? null : Collections.max(gaps) / (double) unitsPerSecond,
                gaps.isEmpty() ? null : nearestRank(gaps, 0.95) / (double) unitsPerSecond,
                thresholdSeconds,
                gapEvents,
                estimatedDrops,
                status);
    }

    static long nearestRank(List<Long> input, double percentile) {
        List<Long> ordered = new ArrayList<>(input);
        Collections.sort(ordered);
        int index = Math.max(0, (int) Math.ceil(percentile * ordered.size()) - 1);
        return ordered.get(index);
    }
}
