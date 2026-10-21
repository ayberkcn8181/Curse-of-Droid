"""Controlled artifact references for tests; never publisher/hardware evidence."""

import hashlib
import json

import pytest


@pytest.fixture
def artifact_manifest():
    def write(path, kind="rom", **overrides):
        content = path.read_bytes()
        document = dict(version=1, filename=path.name, kind=kind, size=len(content),
                        sha256=hashlib.sha256(content).hexdigest(),
                        source_url="https://publisher.example/releases/checksums.txt", devices=["lavender"])
        if kind == "gsi":
            document.update(abi="arm64-v8a", layout="system-as-root")
        document.update(overrides)
        path.with_name(path.name + ".manifest.json").write_text(json.dumps(document), encoding="utf-8")
        return document
    return write
