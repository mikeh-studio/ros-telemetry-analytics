#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

echo "Stopping the Flink TaskManager to exercise checkpoint recovery..."
docker compose stop flink-taskmanager
echo "The JobManager stays online. Restarting the worker in 5 seconds..."
sleep 5
docker compose start flink-taskmanager
echo "Recovery requested. Watch http://localhost:8081 and the Flight Deck incident timeline."
