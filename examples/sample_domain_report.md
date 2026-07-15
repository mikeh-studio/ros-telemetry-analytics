# TUM RGB-D Domain Analysis Result

This sanitized result was generated from the public TUM RGB-D
`rgbd_dataset_freiburg1_xyz` ROS1 bag with the public-test configuration. It
shows the shareable Markdown view; the corresponding Parquet files retain the
per-topic metrics, normalized records, and timestamped anomaly evidence.

## Status

- Messages: **25,626** across **7** topics
- Data health: **warn** (`/tf` maximum gap was 7.16x its mean interval)
- Domain analysis: **ok**
- Domain metric warnings/errors: **0 / 0**
- Domain anomaly events: **0**

## Analysis Coverage

| Normalized payload | Records |
| --- | ---: |
| IMU | 15,158 |
| Transforms | 7,266 |
| Images | 1,596 |
| Odometry | 0 |
| Commands | 0 |
| Diagnostics | 0 |
| Payload extraction errors | 0 |

Zero records means that domain was absent from this bag; it does not mean the
analyzer inferred a clean result for that domain.

## Key Metrics

| Domain | Topic | Metric | Value | Unit |
| --- | --- | --- | ---: | --- |
| image | `/camera/depth/image` | mean depth | 1.164 | m |
| image | `/camera/depth/image` | mean valid-pixel fraction | 0.7569 | ratio |
| image | `/camera/rgb/image_color` | mean intensity | 132.4 | level |
| image | `/camera/rgb/image_color` | minimum sharpness | 4.391 | score |
| image | both image topics | duplicate frames | 0 | frames |
| imu | `/imu` | maximum acceleration magnitude | 13.01 | m/s^2 |
| imu | `/imu` | maximum angular velocity | 0 | rad/s |
| tf | `/world->/kinect` | translation path length | 9.336 | m |
| tf | `/world->/kinect` | maximum translation speed | 0.6169 | m/s |
| tf | all observed frame pairs | directed cycles | 0 | cycles |

## Interpretation

The payload-aware checks found no configured domain anomaly. The separate
transport-health warning still warrants review because a recorder-observed TF
gap can affect downstream consumers even when the decoded motion and sensor
features remain within their configured thresholds.

Metrics are deterministic engineering-triage features, not safety
certification or proof of root cause. Thresholds should be tuned to the robot,
environment, and mission profile before operational use.
