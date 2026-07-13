# Contributing

## Development setup

```bash
make setup
make lint
make test
```

Keep raw ROS bags and generated Parquet outputs under `data/`; both are ignored
except for directory placeholders. Tests must use generated or redistributable
fixtures and must not require ROS 2, CUDA, Docker, or NVIDIA GPU tooling.

Changes to ingestion formats need discovery, reader, failure-isolation, and
idempotency coverage. Changes to analytics need an edge-case fixture that shows
the metric before and after the condition being tested.
