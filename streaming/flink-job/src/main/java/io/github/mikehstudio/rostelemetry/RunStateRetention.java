package io.github.mikehstudio.rostelemetry;

import org.apache.flink.api.common.functions.RuntimeContext;
import org.apache.flink.api.common.state.ValueState;
import org.apache.flink.api.common.state.ValueStateDescriptor;
import org.apache.flink.streaming.api.TimerService;

/** One checkpointed inactivity deadline for an entire key, never independent entry expiration. */
final class RunStateRetention {
    private final ValueState<Long> deadline;
    private final long idleTimeoutMs;

    RunStateRetention(RuntimeContext context, long idleTimeoutMs) {
        deadline = context.getState(new ValueStateDescriptor<>("run-idle-deadline-v1", Long.class));
        this.idleTimeoutMs = validateIdleTimeout(idleTimeoutMs);
    }

    static long configuredIdleTimeoutMs() {
        return parseIdleTimeoutMs(System.getenv("RUN_STATE_IDLE_TIMEOUT_MS"));
    }

    static long parseIdleTimeoutMs(String configured) {
        return validateIdleTimeout(configured == null || configured.isBlank()
                ? StreamingDefaults.RUN_STATE_IDLE_TIMEOUT_MS
                : Long.parseLong(configured.trim()));
    }

    private static long validateIdleTimeout(long idleTimeoutMs) {
        if (idleTimeoutMs <= Math.max(
                StreamingDefaults.ALLOWED_LATENESS_MS, StreamingDefaults.WHOLE_ROBOT_SILENCE_MS)) {
            throw new IllegalArgumentException(
                    "RUN_STATE_IDLE_TIMEOUT_MS must exceed allowed lateness and robot silence timeout");
        }
        return idleTimeoutMs;
    }

    void touch(TimerService timers) throws Exception {
        clear(timers);
        long target = Math.addExact(timers.currentProcessingTime(), idleTimeoutMs);
        deadline.update(target);
        timers.registerProcessingTimeTimer(target);
    }

    boolean expires(long timestamp) throws Exception {
        Long target = deadline.value();
        return target != null && target == timestamp;
    }

    void clear(TimerService timers) throws Exception {
        Long target = deadline.value();
        if (target != null) timers.deleteProcessingTimeTimer(target);
        deadline.clear();
    }
}
