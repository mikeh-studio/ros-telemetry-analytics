FROM ros:jazzy-ros-base@sha256:386d06ec6d4188f731bae5678e07b4cb64a4e4d4152090c0bd1f881dcf7706f5

RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-jazzy-navigation2 ros-jazzy-nav2-bringup \
    ros-jazzy-nav2-minimal-tb3-sim \
    && rm -rf /var/lib/apt/lists/*

ENV ROS_DOMAIN_ID=42 LIBGL_ALWAYS_SOFTWARE=1
COPY demo/simulation/start.py /app/start.py
CMD ["python3", "/app/start.py"]
