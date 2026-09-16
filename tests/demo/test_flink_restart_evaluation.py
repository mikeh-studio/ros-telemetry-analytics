from scripts.run_flink_restart_eval import restored_checkpoint


def test_recovery_requires_restoration_and_a_newer_completed_checkpoint():
    before = {"counts": {"restored": 2}, "latest": {"completed": {"id": 10}}}
    after = {"counts": {"restored": 3}, "latest": {"restored": {"id": 10}, "completed": {"id": 11}}}
    assert restored_checkpoint(before, after)
    after["latest"]["completed"]["id"] = 10
    assert not restored_checkpoint(before, after)
    after["latest"]["completed"]["id"] = 11
    after["counts"]["restored"] = 2
    assert not restored_checkpoint(before, after)
    after["counts"]["restored"] = 3
    after["latest"]["restored"]["id"] = 9
    assert not restored_checkpoint(before, after)
