package io.github.mikehstudio.rostelemetry;

import com.fasterxml.jackson.databind.JsonNode;
import org.apache.flink.api.common.functions.FlatMapFunction;
import org.apache.flink.util.Collector;

final class EnvelopeRouter implements FlatMapFunction<JsonNode, JsonNode> {
    @Override
    public void flatMap(JsonNode envelope, Collector<JsonNode> output) {
        if (!envelope.path("topic").isNull()) {
            output.collect(envelope);
        }
    }
}
