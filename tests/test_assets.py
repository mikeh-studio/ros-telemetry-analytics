from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest
import requests

from isaac_telemetry import assets
from isaac_telemetry.assets import (
    download_asset,
    download_file,
    extract_archive,
    load_asset_config,
    safe_extract,
    sha256_file,
)


def _archive(path: Path, members: list[tuple[tarfile.TarInfo, bytes | None]]) -> Path:
    with tarfile.open(path, "w") as tar_file:
        for member, payload in members:
            tar_file.addfile(member, io.BytesIO(payload) if payload is not None else None)
    return path


def test_safe_extract_allows_regular_files(tmp_path: Path) -> None:
    payload = b"telemetry"
    member = tarfile.TarInfo("bag/data.txt")
    member.size = len(payload)
    archive = _archive(tmp_path / "safe.tar", [(member, payload)])

    with tarfile.open(archive) as tar_file:
        safe_extract(tar_file, tmp_path / "output")

    assert (tmp_path / "output" / "bag" / "data.txt").read_bytes() == payload


@pytest.mark.parametrize("member_name", ["../escape.txt", "/absolute.txt"])
def test_safe_extract_rejects_escaping_paths(tmp_path: Path, member_name: str) -> None:
    member = tarfile.TarInfo(member_name)
    member.size = 1
    archive = _archive(tmp_path / "unsafe.tar", [(member, b"x")])
    with tarfile.open(archive) as tar_file, pytest.raises(RuntimeError, match="Unsafe"):
        safe_extract(tar_file, tmp_path / "output")


def test_safe_extract_rejects_symbolic_links(tmp_path: Path) -> None:
    member = tarfile.TarInfo("link")
    member.type = tarfile.SYMTYPE
    member.linkname = "../outside"
    archive = _archive(tmp_path / "link.tar", [(member, None)])
    with tarfile.open(archive) as tar_file, pytest.raises(RuntimeError, match="member type"):
        safe_extract(tar_file, tmp_path / "output")


def test_asset_config_and_version_parsing(tmp_path: Path) -> None:
    config_path = tmp_path / "assets.yaml"
    config_path.write_text(
        "assets:\n"
        "  sample:\n"
        "    org: nvidia\n"
        "    team: isaac\n"
        "    resource: demo\n"
        "    filename: bag.tar.gz\n"
        "    version: '1.0'\n"
        "    bytes: 10\n"
        f"    sha256: {'a' * 64}\n",
        encoding="utf-8",
    )
    assert load_asset_config(config_path)["sample"]["resource"] == "demo"

    config_path.write_text("assets: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="No assets"):
        load_asset_config(config_path)


class _Response:
    def __init__(self, payload: bytes = b"payload", status_error: bool = False) -> None:
        self.payload = payload
        self.status_error = status_error
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self) -> None:
        if self.status_error:
            raise requests.HTTPError("failed")

    def iter_content(self, chunk_size: int):
        assert chunk_size > 0
        yield self.payload

    def json(self):
        return {"versions": [{"version": "1.0"}]}


class _Session:
    def __init__(self, responses) -> None:
        self.responses = iter(responses)

    def get(self, *_args, **_kwargs):
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_download_file_falls_back_and_verifies_checksum(tmp_path: Path) -> None:
    destination = tmp_path / "asset.tar.gz"
    session = _Session([_Response(status_error=True), _Response(b"verified")])

    digest = download_file(session, ["bad", "good"], destination)

    assert digest == sha256_file(destination)
    assert destination.read_bytes() == b"verified"
    assert download_file(_Session([]), [], destination, digest) == digest
    with pytest.raises(ValueError, match="Checksum mismatch"):
        download_file(_Session([]), [], destination, "0" * 64)


def test_candidate_urls_use_only_the_pinned_version() -> None:
    specification = {
        "org": "nvidia",
        "team": "isaac",
        "resource": "demo resource",
        "filename": "quickstart.tar.gz",
        "version": "2.0",
    }
    urls = assets._candidate_urls(specification)
    assert "versions/2.0" in urls[0]
    assert "%20" in urls[0]
    assert len(urls) == 1


def test_asset_config_requires_reproducibility_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "assets.yaml"
    config_path.write_text(
        "assets:\n  sample:\n    org: nvidia\n    team: isaac\n    resource: demo\n"
        "    filename: bag.tar.gz\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required fields"):
        load_asset_config(config_path)


def test_download_rejects_content_over_expected_size(tmp_path: Path) -> None:
    destination = tmp_path / "asset.tar.gz"

    with pytest.raises(RuntimeError, match="exceeds expected size"):
        download_file(
            _Session([_Response(b"too-large")]),
            ["asset"],
            destination,
            expected_size_bytes=3,
        )

    assert not destination.exists()
    assert not destination.with_suffix(".gz.part").exists()


def test_extract_archive_is_atomic_and_idempotent(tmp_path: Path) -> None:
    payload = b"bag"
    member = tarfile.TarInfo("sample/data.db3")
    member.size = len(payload)
    archive = tmp_path / "asset.tar.gz"
    with tarfile.open(archive, "w:gz") as tar_file:
        tar_file.addfile(member, io.BytesIO(payload))
    digest = sha256_file(archive)
    destination = tmp_path / "extracted"

    extract_archive(archive, destination, digest)
    extract_archive(archive, destination, digest)

    assert (destination / "sample" / "data.db3").read_bytes() == payload
    marker = json.loads((destination / ".extraction-complete.json").read_text())
    assert marker["archive_sha256"] == digest


def test_download_asset_reuses_verified_archive(tmp_path: Path, monkeypatch) -> None:
    archive_root = tmp_path / "downloads"
    extraction_root = tmp_path / "assets"
    archive = archive_root / "sample" / "quickstart.tar.gz"
    archive.parent.mkdir(parents=True)
    payload = b"bag"
    member = tarfile.TarInfo("sample/data.db3")
    member.size = len(payload)
    with tarfile.open(archive, "w:gz") as tar_file:
        tar_file.addfile(member, io.BytesIO(payload))
    monkeypatch.setattr(assets, "DOWNLOAD_DIR", archive_root)
    monkeypatch.setattr(assets, "EXTRACT_DIR", extraction_root)

    output = download_asset(
        "sample",
        {
            "filename": "quickstart.tar.gz",
            "org": "nvidia",
            "team": "isaac",
            "resource": "sample",
            "version": "1.0",
            "sha256": sha256_file(archive),
            "bytes": archive.stat().st_size,
        },
    )

    assert output == extraction_root / "sample"
    assert (output / "sample" / "data.db3").exists()


def test_extract_archive_restores_existing_tree_when_publish_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    archive = tmp_path / "asset.tar.gz"
    member = tarfile.TarInfo("new.txt")
    member.size = 3
    with tarfile.open(archive, "w:gz") as tar_file:
        tar_file.addfile(member, io.BytesIO(b"new"))
    destination = tmp_path / "extracted"
    destination.mkdir()
    (destination / "old.txt").write_text("old", encoding="utf-8")
    real_replace = assets.os.replace

    def fail_stage_publish(source, target):
        if Path(source).name.startswith(".extracted-") and "backup" not in Path(source).name:
            raise OSError("publish failed")
        return real_replace(source, target)

    monkeypatch.setattr(assets.os, "replace", fail_stage_publish)
    with pytest.raises(OSError, match="publish failed"):
        extract_archive(archive, destination, sha256_file(archive))

    assert (destination / "old.txt").read_text() == "old"
