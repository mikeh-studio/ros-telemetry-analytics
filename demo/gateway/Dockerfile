FROM ros:jazzy-ros-base@sha256:386d06ec6d4188f731bae5678e07b4cb64a4e4d4152090c0bd1f881dcf7706f5
RUN apt-get update && apt-get install -y --no-install-recommends python3-venv python3-yaml \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv --system-site-packages /opt/gateway-venv \
    && /opt/gateway-venv/bin/pip install --no-cache-dir aiokafka==0.14.0
ENV PATH="/opt/gateway-venv/bin:${PATH}" PYTHONUNBUFFERED=1
WORKDIR /app
COPY demo /app/demo
COPY configs /app/configs
COPY scripts/ros_gateway_fixture.py /app/scripts/ros_gateway_fixture.py
CMD ["python3", "-m", "demo.gateway.ros_node"]
