import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_reliability_suite as suite


def test_localization_case_requires_telemetry_and_detector_evidence(tmp_path):
    command, evidence = suite.case_command("localization", tmp_path, 80)
    assert "--with-telemetry" in command
    assert evidence == "telemetry-evaluation.json"


def test_successful_process_cannot_hide_failed_evidence_or_skip_required_cases(
    tmp_path, monkeypatch
):
    output = tmp_path / "suite"
    monkeypatch.setattr(
        sys, "argv", ["suite", "--output", str(output), "--cases", "silence", "qos"]
    )
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        destination = Path(command[command.index("--output") + 1])
        destination.mkdir()
        (destination / "evaluation.json").write_text(json.dumps({"passed": False}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(suite.subprocess, "run", run)
    with pytest.raises(SystemExit) as exc:
        suite.main()
    assert exc.value.code == 1
    assert len(calls) == 1
    report = json.loads((output / "evaluation.json").read_text())
    assert not report["passed"]
    assert report["requested_cases"] == ["silence", "qos"]
