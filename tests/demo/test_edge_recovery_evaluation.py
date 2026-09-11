import pytest

from scripts.run_edge_recovery_eval import side_output_counts


def test_sequence_gap_diagnostic_is_not_counted_as_a_late_rejection():
    counts = side_output_counts(
        [
            {"value": {"reason": "sequence_gap"}},
            {"value": {"reason": "beyond_allowed_lateness"}},
            {"value": {"reason": "duplicate"}},
        ]
    )
    assert counts["beyond_allowed_lateness"] == 1
    assert counts["sequence_gap"] == 1
    assert counts["duplicate"] == 1


def test_unknown_stream_disposition_cannot_silently_pass_reconciliation():
    with pytest.raises(ValueError, match="Unclassified"):
        side_output_counts([{"value": {"reason": "new_reason"}}])
