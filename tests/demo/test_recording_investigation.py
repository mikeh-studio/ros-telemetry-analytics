import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

from fastapi import FastAPI

from demo.api.recording_investigation import router
from ros_telemetry_analytics import investigations as evidence


def test_read_only_api_identity_and_interval_errors(tmp_path: Path, monkeypatch):
    app = FastAPI()
    app.include_router(router(tmp_path, tmp_path / "evidence"))
    metadata = {"analysis_id": "a" * 32, "analysis_path": "analysis"}

    def load(root, output, dataset_id, analysis_id=None):
        if dataset_id == "unknown":
            raise KeyError(dataset_id)
        if dataset_id == "missing":
            raise FileNotFoundError()
        if analysis_id and analysis_id != metadata["analysis_id"]:
            raise ValueError("Analysis changed")
        return tmp_path, metadata

    monkeypatch.setattr(evidence, "load_bundle", load)
    monkeypatch.setattr(evidence, "collection", lambda *args: {"datasets": []})
    monkeypatch.setattr(evidence, "public_metadata", lambda *args: dict(metadata))
    monkeypatch.setattr(evidence, "rows", lambda path: [])

    def interval(directory, metadata, start, end, topic, field=None):
        if end <= start:
            raise ValueError("Invalid interval")
        return {"analysis_id": metadata["analysis_id"], "series": []}

    monkeypatch.setattr(evidence, "interval", interval)

    class Client:
        def request(self, method, path, params=None):
            async def call():
                messages = []

                async def receive():
                    return {"type": "http.request", "body": b"", "more_body": False}

                async def send(message):
                    messages.append(message)

                await app(
                    {
                        "type": "http",
                        "http_version": "1.1",
                        "method": method,
                        "scheme": "http",
                        "path": path,
                        "raw_path": path.encode(),
                        "query_string": urlencode(params or {}).encode(),
                        "headers": [],
                        "client": ("test", 123),
                        "server": ("test", 80),
                        "root_path": "",
                    },
                    receive,
                    send,
                )
                return SimpleNamespace(
                    status_code=messages[0]["status"],
                    json=lambda: json.loads(b"".join(m.get("body", b"") for m in messages)),
                )

            return asyncio.run(call())

        def get(self, path, params=None):
            return self.request("GET", path, params)

        def post(self, path):
            return self.request("POST", path)

    client = Client()
    assert client.get("/api/investigations").json() == {"datasets": []}
    assert client.get("/api/investigations/test").json() == {**metadata, "continuity_checks": []}
    assert client.get("/api/investigations/unknown").status_code == 404
    assert client.get("/api/investigations/missing").status_code == 404
    path = "/api/investigations/test/interval"
    query = {"analysis_id": "a" * 32, "start_s": 0, "end_s": 1}
    assert client.get(path, params=query).status_code == 200
    assert client.get(path, params={**query, "analysis_id": "b" * 32}).status_code == 409
    assert client.get(path, params={**query, "start_s": 2}).status_code == 400
    assert client.get(path, params={**query, "start_s": -1}).status_code == 422
    assert client.post("/api/investigations/test").status_code == 405
