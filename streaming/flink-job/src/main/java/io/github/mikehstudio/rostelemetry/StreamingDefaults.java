package io.github.mikehstudio.rostelemetry;

import java.time.Duration;
import org.apache.flink.api.common.state.StateTtlConfig;

/** Java runtime values locked to configs/streaming_demo.yaml by contract tests. */
final class StreamingDefaults {
    static final long WINDOW_MS = 10_000;
    static final long SLIDE_MS = 1_000;
    static final long RECOVERY_GATE_MS = 1_000;
    static final long MAXIMUM_OUT_OF_ORDERNESS_MS = 2_000;
    static final long ALLOWED_LATENESS_MS = 5_000;
    static final long IDLE_PARTITION_TIMEOUT_MS = 3_000;
    static final long WHOLE_ROBOT_SILENCE_MS = 10_000;
    static final double MINIMUM_RATE_RATIO = 0.8;
    static final double MAXIMUM_RATE_RATIO = 1.2;
    static final double GAP_THRESHOLD_MULTIPLIER = 1.5;
    static final int EXPECTED_TOPIC_COUNT = 4;
    static final long STATE_TTL_MINUTES = 12;
    static final long CHECKPOINT_INTERVAL_MS = 5_000;
    static final long CHECKPOINT_MIN_PAUSE_MS = 2_000;
    static final long CHECKPOINT_TIMEOUT_MS = 60_000;
    static final int RESTART_ATTEMPTS = 3;
    static final long RESTART_DELAY_MS = 2_000;
    static final int KAFKA_TRANSACTION_TIMEOUT_MS = 900_000;

    static StateTtlConfig stateTtl() {
        return StateTtlConfig.newBuilder(Duration.ofMinutes(STATE_TTL_MINUTES))
                .setUpdateType(StateTtlConfig.UpdateType.OnCreateAndWrite)
                .neverReturnExpired()
                .build();
    }

    private StreamingDefaults() {}
}
