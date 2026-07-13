# Isaac Visual SLAM Sample Result

This sanitized result was generated from NVIDIA's Visual SLAM quickstart bag
with the default configuration.

| Result | Value |
| --- | ---: |
| Bags discovered | 1 |
| Bags processed | 1 |
| Messages indexed | 957 |
| Topics discovered | 10 |
| Quality checks | 6 |
| Overall status | `warn` |
| Warnings | 6 |
| Pipeline failures | 0 |

The warning set identified three image topics with cadence gaps, a `/tf`
continuity outlier, back-camera image skew above 5 ms, and one unmatched frame
on each side of the front-camera stereo stream. The result demonstrates why the
pipeline separates transport health from ingestion success: the bag processed
correctly while its timing still warrants review.

Generated data is intentionally excluded from Git. Run `make analyze` to inspect
the complete Parquet records locally.
