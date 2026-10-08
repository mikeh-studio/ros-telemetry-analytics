# Security Policy

## Supported versions

Security fixes are made on the default branch (`main`) and included in the next
tagged release. Older releases are not patched.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private
security advisory workflow for the repository and include reproduction steps,
affected inputs, and the expected impact.

## Trust model

Recordings, uploaded files and downloaded archives are treated as untrusted input.

- **Archive extraction** rejects links, special files, absolute paths and
  parent-path traversal, and publishes extracted files atomically.
- **Recording analysis** reads bag metadata and message timing for every topic.
  For supported message types (odometry, IMU, velocity commands, transforms,
  diagnostics, images, laser scans and point clouds), payloads are deserialized
  with [`rosbags`](https://gitlab.com/ternaris/rosbags). Deserialization failures
  are counted and reported; timing analysis still completes.
- **Uploads** to the local API are limited by `DATASET_UPLOAD_MAX_BYTES`
  (default 4 GiB) and stored in a dedicated Docker volume.

The Docker Compose stack is a local development demo. Its API, web UI and Flink
dashboard have no authentication and publish ports on the host. Do not expose them
to an untrusted network.
