"""io.save_json is atomic: readers see the old file or the new one, and a failed write keeps the old one."""
import json
import os

import pytest

from autograde import io


def test_save_json_replaces_the_whole_file(tmp_path):
    p = tmp_path / "c.json"
    io.save_json({"a": 1}, p)
    io.save_json({"b": 2}, p)
    assert json.loads(p.read_text(encoding="utf-8")) == {"b": 2}
    assert [f.name for f in tmp_path.iterdir()] == ["c.json"]  # no temp file left behind


def test_failed_write_keeps_the_old_file(tmp_path, monkeypatch):
    p = tmp_path / "c.json"
    io.save_json({"a": 1}, p)

    def disk_full(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", disk_full)
    with pytest.raises(OSError):
        io.save_json({"b": 2}, p)
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
    assert [f.name for f in tmp_path.iterdir()] == ["c.json"]
