package io.github.mikehstudio.rostelemetry;

import org.apache.flink.core.io.SimpleVersionedSerializer;
import org.apache.flink.streaming.api.functions.sink.filesystem.BucketAssigner;
import org.apache.flink.streaming.api.functions.sink.filesystem.bucketassigners.SimpleVersionedStringSerializer;

final class RunBucketAssigner implements BucketAssigner<String, String> {
    @Override
    public String getBucketId(String value, Context context) {
        try {
            String runId = JsonSupport.MAPPER.readTree(value).path("run_id").asText("unknown-run");
            return runId + "/topic_health";
        } catch (Exception exception) {
            return "invalid/topic_health";
        }
    }

    @Override
    public SimpleVersionedSerializer<String> getSerializer() {
        return SimpleVersionedStringSerializer.INSTANCE;
    }
}
