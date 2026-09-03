package io.github.mikehstudio.rostelemetry;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import org.apache.flink.api.common.eventtime.WatermarkStrategy;
import org.apache.flink.api.common.serialization.SimpleStringEncoder;
import org.apache.flink.api.common.serialization.SimpleStringSchema;
import org.apache.flink.configuration.Configuration;
import org.apache.flink.configuration.ExternalizedCheckpointRetention;
import org.apache.flink.configuration.RestartStrategyOptions;
import org.apache.flink.connector.base.DeliveryGuarantee;
import org.apache.flink.connector.file.sink.FileSink;
import org.apache.flink.connector.kafka.sink.KafkaSink;
import org.apache.flink.connector.kafka.source.KafkaSource;
import org.apache.flink.connector.kafka.source.enumerator.initializer.OffsetsInitializer;
import org.apache.flink.core.fs.Path;
import org.apache.flink.streaming.api.CheckpointingMode;
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.datastream.SingleOutputStreamOperator;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.streaming.api.functions.sink.filesystem.rollingpolicies.OnCheckpointRollingPolicy;

public final class TelemetryStreamingJob {
    private static final String SOURCE_TOPIC = "telemetry.events.v1";
    private static final String METRICS_TOPIC = "telemetry.metrics.v1";
    private static final String ANOMALIES_TOPIC = "telemetry.anomalies.v1";
    private static final String LATE_TOPIC = "telemetry.late.v1";
    private static final String DEAD_LETTER_TOPIC = "telemetry.dead-letter.v1";

    private TelemetryStreamingJob() {}

    public static void main(String[] args) throws Exception {
        String bootstrapServers = env("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092");
        String outputRoot = env("DEMO_OUTPUT_URI", "file:///opt/demo-output");
        StreamExecutionEnvironment environment = StreamExecutionEnvironment.getExecutionEnvironment();
        configureReliability(environment);

        KafkaSource<String> source = KafkaSource.<String>builder()
                .setBootstrapServers(bootstrapServers)
                .setTopics(SOURCE_TOPIC)
                .setGroupId("robot-telemetry-flink-v1")
                .setStartingOffsets(OffsetsInitializer.earliest())
                .setValueOnlyDeserializer(new SimpleStringSchema())
                .build();

        DataStream<String> raw = environment.fromSource(
                source, WatermarkStrategy.noWatermarks(), "telemetry-kafka-source");
        SingleOutputStreamOperator<JsonNode> parsed = raw.process(new ParseEnvelopeFunction());
        parsed.getSideOutput(ParseEnvelopeFunction.DEAD_LETTER)
                .sinkTo(kafkaSink(bootstrapServers, DEAD_LETTER_TOPIC, "dead-letter-v1", "dead"))
                .name("dead-letter-kafka-sink");

        DataStream<String> sequenceEvidence = parsed
                .filter(TelemetryStreamingJob::isTelemetry)
                .keyBy(TelemetryStreamingJob::robotEnvelopeKey)
                .process(new SequenceEvidenceProcessor())
                .name("robot-sequence-transport-evidence");

        DataStream<JsonNode> robotLifecycle = parsed
                .filter(TelemetryStreamingJob::isLifecycle)
                .name("robot-lifecycle");
        DataStream<String> lifecycleStatus = robotLifecycle
                .map(TelemetryStreamingJob::runStatusMetric)
                .name("run-status-metrics");
        DataStream<String> registrationStatus = parsed
                .filter(node -> node.path("envelope_type").asText().equals("topic_registered"))
                .keyBy(TelemetryStreamingJob::robotEnvelopeKey)
                .process(new RunCoordinator())
                .name("run-registration-coordinator");

        DataStream<JsonNode> watermarked = parsed.assignTimestampsAndWatermarks(
                WatermarkStrategy.<JsonNode>forBoundedOutOfOrderness(
                                Duration.ofMillis(StreamingDefaults.MAXIMUM_OUT_OF_ORDERNESS_MS))
                        .withTimestampAssigner((event, previous) -> event.path("stream_timestamp_ms").asLong())
                        .withIdleness(
                                Duration.ofMillis(StreamingDefaults.IDLE_PARTITION_TIMEOUT_MS)));
        DataStream<JsonNode> routed = watermarked.flatMap(new EnvelopeRouter()).name("route-topic-lifecycle");
        SingleOutputStreamOperator<String> topicMetrics = routed
                .keyBy(TelemetryStreamingJob::topicKey)
                .process(new TopicHealthProcessor())
                .name("stateful-topic-health");

        DataStream<String> topicAnomalies = topicMetrics.getSideOutput(TopicHealthProcessor.ANOMALIES);
        topicMetrics.getSideOutput(TopicHealthProcessor.LATE_EVENTS)
                .union(sequenceEvidence)
                .sinkTo(kafkaSink(bootstrapServers, LATE_TOPIC, "late-v1", "late"))
                .name("late-event-kafka-sink");

        SingleOutputStreamOperator<String> livenessMetrics = watermarked
                .filter(TelemetryStreamingJob::isRobotLivenessInput)
                .keyBy(TelemetryStreamingJob::robotEnvelopeKey)
                .process(new RobotLivenessProcessor())
                .name("robot-processing-time-watchdog");

        DataStream<String> livenessAnomalies =
                livenessMetrics.getSideOutput(RobotLivenessProcessor.ANOMALIES);
        DataStream<String> anomalies = topicAnomalies.union(livenessAnomalies);
        SingleOutputStreamOperator<String> robotMetrics = topicMetrics
                .filter(TelemetryStreamingJob::isTopicWindowMetric)
                .union(topicAnomalies, livenessMetrics, livenessAnomalies)
                .keyBy(TelemetryStreamingJob::robotKey)
                .process(new RobotHealthProcessor())
                .name("robot-health-aggregate");
        DataStream<String> summaryReady = topicMetrics
                .filter(TelemetryStreamingJob::isMissionSummary)
                .keyBy(TelemetryStreamingJob::robotKey)
                .process(new SummaryCoordinator())
                .name("mission-summary-coordinator");
        DataStream<String> metrics = topicMetrics.union(
                robotMetrics, lifecycleStatus, registrationStatus, summaryReady);

        metrics.sinkTo(kafkaSink(bootstrapServers, METRICS_TOPIC, "metrics-v1", "metric"))
                .name("metrics-exactly-once-kafka-sink");
        anomalies.sinkTo(kafkaSink(bootstrapServers, ANOMALIES_TOPIC, "anomalies-v1", "anomaly"))
                .name("anomalies-exactly-once-kafka-sink");

        FileSink<String> summaries = FileSink
                .forRowFormat(new Path(outputRoot), new SimpleStringEncoder<String>(StandardCharsets.UTF_8.name()))
                .withBucketAssigner(new RunBucketAssigner())
                .withRollingPolicy(OnCheckpointRollingPolicy.build())
                .build();
        metrics.filter(TelemetryStreamingJob::isMissionSummary)
                .sinkTo(summaries)
                .name("durable-mission-summary-files");

        environment.execute("Robot Telemetry Flight Deck");
    }

    private static void configureReliability(StreamExecutionEnvironment environment) {
        environment.enableCheckpointing(
                StreamingDefaults.CHECKPOINT_INTERVAL_MS, CheckpointingMode.EXACTLY_ONCE);
        environment.getCheckpointConfig()
                .setMinPauseBetweenCheckpoints(StreamingDefaults.CHECKPOINT_MIN_PAUSE_MS);
        environment.getCheckpointConfig()
                .setCheckpointTimeout(StreamingDefaults.CHECKPOINT_TIMEOUT_MS);
        environment.getCheckpointConfig().setMaxConcurrentCheckpoints(1);
        environment.getCheckpointConfig().setExternalizedCheckpointRetention(
                ExternalizedCheckpointRetention.RETAIN_ON_CANCELLATION);
        Configuration restart = new Configuration();
        restart.set(RestartStrategyOptions.RESTART_STRATEGY, "fixed-delay");
        restart.set(
                RestartStrategyOptions.RESTART_STRATEGY_FIXED_DELAY_ATTEMPTS,
                StreamingDefaults.RESTART_ATTEMPTS);
        restart.set(
                RestartStrategyOptions.RESTART_STRATEGY_FIXED_DELAY_DELAY,
                Duration.ofMillis(StreamingDefaults.RESTART_DELAY_MS));
        environment.configure(restart);
    }

    private static KafkaSink<String> kafkaSink(
            String bootstrapServers, String topic, String transactionalPrefix, String kind) {
        return KafkaSink.<String>builder()
                .setBootstrapServers(bootstrapServers)
                .setRecordSerializer(new JsonKeyedSerializationSchema(topic, kind))
                .setDeliveryGuarantee(DeliveryGuarantee.EXACTLY_ONCE)
                .setTransactionalIdPrefix("robot-telemetry-" + transactionalPrefix + "-")
                .setProperty(
                        "transaction.timeout.ms",
                        String.valueOf(StreamingDefaults.KAFKA_TRANSACTION_TIMEOUT_MS))
                .build();
    }

    private static String topicKey(JsonNode envelope) {
        return envelope.path("run_id").asText()
                + "|"
                + envelope.path("robot_id").asText()
                + "|"
                + envelope.path("topic").asText();
    }

    private static String robotEnvelopeKey(JsonNode envelope) {
        return envelope.path("run_id").asText() + "|" + envelope.path("robot_id").asText();
    }

    private static String robotKey(String metric) throws Exception {
        JsonNode node = JsonSupport.MAPPER.readTree(metric);
        return node.path("run_id").asText() + "|" + node.path("robot_id").asText();
    }

    private static boolean isTopicWindowMetric(String metric) throws Exception {
        return JsonSupport.MAPPER.readTree(metric).path("metric_type").asText().equals("topic_window");
    }

    private static boolean isMissionSummary(String metric) throws Exception {
        return JsonSupport.MAPPER.readTree(metric).path("metric_type").asText().equals("mission_summary");
    }

    private static boolean isLifecycle(JsonNode envelope) {
        if (!envelope.path("topic").isNull()) return false;
        return switch (envelope.path("envelope_type").asText()) {
            case "run_started", "run_paused", "run_resumed", "run_aborted", "run_failed", "run_ended" -> true;
            default -> false;
        };
    }

    private static boolean isTelemetry(JsonNode envelope) {
        return envelope.path("envelope_type").asText().equals("telemetry");
    }

    private static boolean isRobotLivenessInput(JsonNode envelope) {
        return isTelemetry(envelope) || isLifecycle(envelope);
    }

    private static String runStatusMetric(JsonNode envelope) {
        String type = envelope.path("envelope_type").asText();
        String status = switch (type) {
            case "run_started" -> "starting";
            case "run_paused" -> "paused";
            case "run_resumed" -> "running";
            case "run_aborted" -> "aborted";
            case "run_failed" -> "failed";
            case "run_ended" -> "finalizing";
            default -> "unknown";
        };
        ObjectNode node = JsonSupport.object();
        node.put("schema_version", 1);
        node.put("metric_id", JsonSupport.sha256(1, "run_status", envelope.path("envelope_id").asText()));
        node.put("metric_type", "run_status");
        node.put("run_id", envelope.path("run_id").asText());
        node.put("robot_id", envelope.path("robot_id").asText());
        node.putNull("topic");
        node.putNull("window_start_ms");
        node.putNull("window_end_ms");
        node.put("revision", 0);
        node.put("stream_timestamp_ms", envelope.path("stream_timestamp_ms").asLong());
        ObjectNode payload = node.putObject("payload");
        payload.put("status", status);
        payload.put("source", "recorded_replay");
        JsonNode body = envelope.path("body");
        copyText(body, payload, "dataset_id");
        copyText(body, payload, "dataset_name");
        copyText(body, payload, "source_format");
        if (body.has("mission_duration_ms")) {
            payload.put("mission_duration_ms", body.path("mission_duration_ms").asLong());
        }
        if (body.has("expected_topic_count")) {
            payload.put("expected_topic_count", body.path("expected_topic_count").asInt());
        }
        return JsonSupport.write(node);
    }

    private static void copyText(JsonNode source, ObjectNode destination, String field) {
        if (source.hasNonNull(field)) destination.put(field, source.path(field).asText());
    }

    private static String env(String name, String defaultValue) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? defaultValue : value;
    }
}
