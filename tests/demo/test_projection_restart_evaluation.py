import asyncio
import json
import sys
from collections import namedtuple
from types import SimpleNamespace

from scripts.probe_kafka_offsets import main as probe
from scripts.run_projection_restart_eval import caught_up


def test_catchup_requires_every_frozen_partition_and_nonempty_boundary():
    snapshot = {
        "consumer_offsets": [
            {"topic": "metrics", "partition": 0, "next_offset": 100},
            {"topic": "metrics", "partition": 1, "next_offset": 50},
        ]
    }
    assert caught_up(snapshot, {"metrics:0": 90, "metrics:1": 50})
    assert not caught_up(snapshot, {"metrics:0": 90, "metrics:1": 51})
    assert not caught_up(snapshot, {"anomalies:0": 1})
    assert not caught_up(snapshot, {})


def test_probe_excludes_control_markers_and_records_after_frozen_end(monkeypatch, capsys):
    partition = namedtuple("Partition", "topic partition")
    metrics, anomalies = partition("metrics", 0), partition("anomalies", 0)

    class Consumer:
        def __init__(self, *args, **kwargs):
            self.positions = {}

        async def start(self):
            pass

        async def stop(self):
            pass

        def assignment(self):
            return {metrics, anomalies}

        async def end_offsets(self, partitions):
            return {metrics: 5, anomalies: 3}

        def seek(self, p, value):
            self.positions[p] = value

        async def position(self, p):
            return self.positions[p]

        async def getmany(self, **kwargs):
            self.positions.update({metrics: 7, anomalies: 3})
            return {metrics: [SimpleNamespace(offset=3), SimpleNamespace(offset=6)]}

    monkeypatch.setitem(sys.modules, "aiokafka", SimpleNamespace(AIOKafkaConsumer=Consumer))
    asyncio.run(probe({"metrics:0": 2, "anomalies:0": 2}))
    assert json.loads(capsys.readouterr().out) == {"metrics:0": 4, "anomalies:0": 2}
