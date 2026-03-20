"""Unit tests for line record model."""

from __future__ import annotations

from ssh_logstream.models import LineRecord


def test_line_record_fields_are_exposed() -> None:
    record = LineRecord(text="hello", byte_length=5)

    assert record.text == "hello"
    assert record.byte_length == 5

