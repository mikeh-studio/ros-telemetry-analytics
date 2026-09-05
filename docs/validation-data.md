# Validation datasets

[Back to README](../README.md)

Validated TUM RGB-D and TUM VI datasets provide independent ROS 1 coverage and
healthy-data robustness checks:

```bash
make analyze-public-data
```

Optional NVIDIA Isaac ROS archives provide larger ROS 2 validation cases:

```bash
make download-visual-slam
make download-nvblox
```

Downloads remain ignored by Git. Their sources, checksums, licenses, validation
results, and known caveats are recorded in
[`configs/public_test_datasets.yaml`](../configs/public_test_datasets.yaml) and the
[`asset configuration`](../configs/asset_sources.yaml). NVIDIA data is subject to
upstream terms; this independent project is not affiliated with or endorsed by
NVIDIA.
