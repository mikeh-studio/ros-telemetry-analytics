# Scripts

Run these from the repository root with the project virtual environment, for
example `.venv/bin/python scripts/smoke_demo.py`. Several scripts are mounted into
containers by file name, so they stay in one flat directory.

## Demo and CI

| Script | Purpose |
| --- | --- |
| `smoke_demo.py` | Run one recorded Compose mission and check its result (used by CI). |
| `compare_demo_oracle.py` | Compare Flink mission summaries with the batch-analysis oracle (used by CI). |
| `demo_recovery.sh` | Restart the Flink TaskManager during an active mission. |
| `nav2_mission.py` | Bounded mission for the bundled Gazebo sandbox (used by `compose.simulation.yaml`). |
| `ros_gateway_fixture.py` | Publishes real ROS messages for gateway transport tests (copied into the gateway image). |

## Recording datasets and evidence

See [Recording investigations](../docs/recording-investigations.md#reproduce-locally).

| Script | Purpose |
| --- | --- |
| `fetch_comparison_data.py` | Download the comparison recordings without replacing existing files. |
| `prepare_investigations.py` | Build offline incident evidence for registered recordings. |
| `curate_investigations.py` | Attach reviewed case notes to a prepared analysis. |
| `audit_dataset_inventory.py` | Inventory local recordings and record reader checks. |

## Reliability experiments

Entry points. Commands and pass criteria are in the [Live ROS 2 runbook](../docs/live-ros2.md#fault-experiments).

| Script | Purpose |
| --- | --- |
| `run_reliability_suite.py` | Run the experiments below in sequence and keep every result. |
| `run_gateway_eval.py` | DDS silence, QoS repair, duplicate and delay experiments. |
| `run_edge_recovery_eval.py` | Disconnect and crash a gateway, then reconcile its durable backlog. |
| `run_fleet_isolation_eval.py` | Three concurrent robots with one gateway outage. |
| `run_flink_restart_eval.py` | Hard-stop a Flink worker and check checkpoint restoration. |
| `run_projection_restart_eval.py` | Interrupt the API projection and measure catch-up. |
| `run_nav2_localization_eval.py` | Controlled localization disturbance in the Nav2 sandbox. |
| `evaluate_signal_projection.py` | Reconcile sampled incident signals with source envelopes. |

Helpers called by the entry points:

| Script | Purpose |
| --- | --- |
| `capture_gateway_run.py` | Capture a bounded Kafka offset snapshot for one run. |
| `probe_kafka_offsets.py` | Read a frozen Kafka offset boundary. |
| `gateway_fault_transport.py` | Test-only shim that repeats or holds selected envelopes. |
| `nav2_localization_fault.py` | Reset the AMCL estimate in the Gazebo sandbox. |
| `evaluate_gateway_run.py` | Evaluate a transport run against its publisher ledger. |
| `evaluate_transport_fault.py` | Check injected duplicate and delay dispositions. |
| `evaluate_nav2_telemetry.py` | Evaluate Nav2 telemetry and relative-motion detection. |
