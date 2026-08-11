from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_compose_exposes_one_command_demo_contract() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert set(services) == {
        "kafka-storage-init",
        "kafka",
        "kafka-init",
        "flink-storage-init",
        "flink-jobmanager",
        "flink-taskmanager",
        "replayer",
        "api",
        "web",
    }
    assert services["web"]["ports"] == ["3000:80"]
    assert services["api"]["ports"] == ["8000:8000"]
    assert services["flink-jobmanager"]["ports"] == ["8081:8081"]
    assert services["api"]["depends_on"]["flink-taskmanager"]["condition"] == "service_started"
    assert (
        services["kafka"]["depends_on"]["kafka-storage-init"]["condition"]
        == "service_completed_successfully"
    )
    assert services["kafka"]["environment"]["KAFKA_LOG_DIRS"] == "/tmp/kraft-combined-logs"
    assert services["kafka"]["environment"]["CLUSTER_ID"]
    assert "kafka-data:/tmp/kraft-combined-logs" in services["kafka"]["volumes"]
    assert (
        "chown -R appuser:appuser /tmp/kraft-combined-logs"
        in services["kafka-storage-init"]["command"]
    )
    assert (
        "file:///checkpoints"
        in compose["services"]["flink-jobmanager"]["environment"]["FLINK_PROPERTIES"]
    )
    assert (
        services["flink-jobmanager"]["depends_on"]["flink-storage-init"]["condition"]
        == "service_completed_successfully"
    )
    assert services["flink-storage-init"]["user"] == "root"
    assert (
        "chown -R flink:flink /checkpoints /opt/demo-output"
        in services["flink-storage-init"]["command"]
    )
    assert "demo-output:/opt/demo-output" in services["flink-taskmanager"]["volumes"]
    assert "demo-data:/app/data/demo:ro" in services["api"]["volumes"]
    assert "demo-output:/app/data/demo-output:ro" in services["api"]["volumes"]
    assert "demo-output" in compose["volumes"]
    init_script = services["kafka-init"]["command"][-1]
    assert "create_topic telemetry.events.v1 4" in init_script
    for topic in [
        "telemetry.metrics.v1",
        "telemetry.anomalies.v1",
        "telemetry.late.v1",
        "telemetry.dead-letter.v1",
    ]:
        assert f"create_topic {topic} 1" in init_script
    assert "/var/run/docker.sock" not in (ROOT / "compose.yaml").read_text(encoding="utf-8")


def test_container_versions_and_entrypoints_are_pinned() -> None:
    compose_text = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    flink_dockerfile = (ROOT / "streaming/flink-job/Dockerfile").read_text(encoding="utf-8")
    pom = (ROOT / "streaming/flink-job/pom.xml").read_text(encoding="utf-8")
    job = (
        ROOT
        / "streaming/flink-job/src/main/java/io/github/mikehstudio/rostelemetry"
        / "TelemetryStreamingJob.java"
    ).read_text(encoding="utf-8")

    assert "apache/kafka:4.1.2" in compose_text
    assert "FROM flink:2.2.1-java17" in flink_dockerfile
    assert "maven:3.9.11-eclipse-temurin-17" in flink_dockerfile
    assert "RUN mvn --batch-mode verify" in flink_dockerfile
    assert "verify package" not in flink_dockerfile
    assert "<flink.version>2.2.1</flink.version>" in pom
    assert "<flink.kafka.version>5.0.0-2.2</flink.kafka.version>" in pom
    assert "DeliveryGuarantee.EXACTLY_ONCE" in job
    assert ".setTransactionalIdPrefix(" in job
    assert '"transaction.timeout.ms"' in job
    for identity in ["metrics-v1", "anomalies-v1", "late-v1", "dead-letter-v1"]:
        assert identity in job
    assert "KAFKA_TRANSACTION_MAX_TIMEOUT_MS: 900000" in compose_text
