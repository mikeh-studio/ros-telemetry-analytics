FROM maven:3.9.11-eclipse-temurin-17 AS build

WORKDIR /build/streaming/flink-job
COPY streaming/flink-job/pom.xml ./pom.xml
COPY schemas /build/schemas
COPY configs /build/configs
RUN mvn --batch-mode dependency:go-offline
COPY streaming/flink-job/src ./src
RUN mvn --batch-mode verify package

FROM flink:2.2.1-java17

USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
USER flink

COPY --from=build /build/streaming/flink-job/target/robot-telemetry-flink-job-0.1.0.jar /opt/flink/usrlib/robot-telemetry-flink-job.jar
