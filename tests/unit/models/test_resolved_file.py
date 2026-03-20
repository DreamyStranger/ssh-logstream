"""Unit tests for resolved file model."""

from __future__ import annotations

from ssh_logstream.models import ResolvedFile


def test_resolved_file_fields_are_exposed() -> None:
    resolved = ResolvedFile(folder="/var/log", filename="app.log", path="/var/log/app.log")

    assert resolved.folder == "/var/log"
    assert resolved.filename == "app.log"
    assert resolved.path == "/var/log/app.log"

