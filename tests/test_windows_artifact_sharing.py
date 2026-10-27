"""Native handle-sharing checks; actual write/delete exclusion needs Windows."""
import os

import pytest

from curseofdroid.flash.artifacts import _open_regular


pytestmark = pytest.mark.skipif(os.name != "nt", reason="requires Windows file sharing")


@pytest.mark.parametrize("operation", ["write", "replace"])
def test_read_handle_allows_readers_but_excludes_mutation_until_closed(tmp_path, operation):
    path, replacement = tmp_path / "input.zip", tmp_path / "replacement.zip"
    path.write_bytes(b"original")
    replacement.write_bytes(b"replaced")

    def mutate():
        if operation == "write":
            path.write_bytes(b"modified")  # same-size edits must also be denied
        else:
            os.replace(replacement, path)

    with _open_regular(path) as stream:
        with _open_regular(path) as other:
            assert other.read() == stream.read() == b"original"
        with pytest.raises(PermissionError):
            mutate()
        assert path.read_bytes() == b"original"
    mutate()
    assert path.read_bytes() == (b"modified" if operation == "write" else b"replaced")


def test_existing_writer_prevents_verified_reader_open(tmp_path):
    path = tmp_path / "input.zip"
    path.write_bytes(b"original")
    with path.open("r+b"):
        with pytest.raises(PermissionError):
            _open_regular(path)
    with _open_regular(path) as stream:
        assert stream.read() == b"original"
