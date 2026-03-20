"""Unit tests for the core byte-to-line streaming pipeline."""

from __future__ import annotations

import pytest

from ssh_logstream import LineStreamerConfig
from ssh_logstream.errors import LineTooLongError
from ssh_logstream.streaming import LineStreamerCore


def test_line_streamer_core_emits_lines_and_final_partial_line() -> None:
    core = LineStreamerCore(LineStreamerConfig(chunk_size=4, max_line_bytes=16))

    lines = [record.text for record in core.iter_lines([b"alpha\r\nbe", b"ta\n\nome", b"ga"])]

    assert lines == ["alpha", "beta", "", "omega"]


def test_line_streamer_core_iter_text_emits_lines_and_final_partial_line() -> None:
    core = LineStreamerCore(LineStreamerConfig(chunk_size=4, max_line_bytes=16))

    lines = list(core.iter_text([b"alpha\r\nbe", b"ta\n\nome", b"ga"]))

    assert lines == ["alpha", "beta", "", "omega"]


def test_line_streamer_core_enforces_line_limit_with_replace_errors() -> None:
    core = LineStreamerCore(
        LineStreamerConfig(
            chunk_size=1,
            max_line_bytes=1,
            encoding="utf-8",
            errors="replace",
        )
    )

    with pytest.raises(LineTooLongError):
        list(core.iter_lines([b"\xff", b"\xff"]))


def test_line_streamer_core_supports_utf16_line_boundaries() -> None:
    core = LineStreamerCore(
        LineStreamerConfig(
            chunk_size=4,
            max_line_bytes=32,
            encoding="utf-16-le",
            errors="strict",
        )
    )

    payload = "alpha\nbeta".encode("utf-16-le")
    lines = [record.text for record in core.iter_lines([payload[:5], payload[5:]])]

    assert lines == ["alpha", "beta"]


def test_line_streamer_core_iter_text_supports_utf16_line_boundaries() -> None:
    core = LineStreamerCore(
        LineStreamerConfig(
            chunk_size=4,
            max_line_bytes=32,
            encoding="utf-16-le",
            errors="strict",
        )
    )

    payload = "alpha\nbeta".encode("utf-16-le")
    lines = list(core.iter_text([payload[:5], payload[5:]]))

    assert lines == ["alpha", "beta"]
