PYTHON ?= .venv/bin/python
SYSTEM_PYTHON ?= python3
CONFIG ?= configs/pipeline.yaml

.PHONY: setup test lint format discover analyze analyze-public-data force-analyze download-visual-slam download-nvblox clean-derived

setup:
	$(SYSTEM_PYTHON) -m venv .venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest --cov=isaac_telemetry --cov-report=term-missing --cov-fail-under=80

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

discover:
	$(PYTHON) -m isaac_telemetry discover --config $(CONFIG)

analyze:
	$(PYTHON) -m isaac_telemetry analyze --config $(CONFIG)

analyze-public-data:
	$(PYTHON) -m isaac_telemetry analyze --config configs/public_test_pipeline.yaml

force-analyze:
	$(PYTHON) -m isaac_telemetry analyze --config $(CONFIG) --force

download-visual-slam:
	$(PYTHON) -m isaac_telemetry download --asset visual_slam

download-nvblox:
	$(PYTHON) -m isaac_telemetry download --asset nvblox

clean-derived:
	$(PYTHON) -c 'import shutil; from pathlib import Path; shutil.rmtree(Path("data/bronze/bags"), ignore_errors=True)'
