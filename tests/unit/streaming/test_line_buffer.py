"""Unit tests for bounded line buffering."""

from __future__ import annotations

import pytest

from ssh_logstream import LineTooLongError
from ssh_logstream.streaming import IncrementalDecoder, LineBuffer


def _append(buffer: LineBuffer, decoder: IncrementalDecoder, chunk: bytes) -> None:
    buffer.append_chunk(chunk, decoded_text=decoder.decode_chunk(chunk))


def test_line_buffer_emits_normalized_lines() -> None:
    buffer = LineBuffer(encoding="utf-8", errors="strict", max_line_bytes=16)
    decoder = IncrementalDecoder(encoding="utf-8", errors="strict")

    _append(buffer, decoder, b"alpha\r\nbeta\n\ngamma")

    lines = list(buffer.pop_lines())
    final_line = buffer.pop_final_line()

    assert [line.text for line in lines] == ["alpha", "beta", ""]
    assert final_line is not None
    assert final_line.text == "gamma"


def test_line_buffer_enforces_max_line_bytes() -> None:
    buffer = LineBuffer(encoding="utf-8", errors="strict", max_line_bytes=4)
    decoder = IncrementalDecoder(encoding="utf-8", errors="strict")

    with pytest.raises(LineTooLongError):
        _append(buffer, decoder, b"abcde")
        buffer.ensure_limit()


def test_line_buffer_tracks_raw_bytes_with_replace_errors() -> None:
    buffer = LineBuffer(encoding="utf-8", errors="replace", max_line_bytes=1)
    decoder = IncrementalDecoder(encoding="utf-8", errors="replace")

    _append(buffer, decoder, b"\xff")

    with pytest.raises(LineTooLongError):
        _append(buffer, decoder, b"\xff")
        buffer.ensure_limit()


def test_line_buffer_splits_lines_for_utf16() -> None:
    buffer = LineBuffer(encoding="utf-16-le", errors="strict", max_line_bytes=32)
    decoder = IncrementalDecoder(encoding="utf-16-le", errors="strict")

    _append(buffer, decoder, "alpha\nbeta".encode("utf-16-le"))

    lines = list(buffer.pop_lines())
    final_line = buffer.pop_final_line()

    assert [line.text for line in lines] == ["alpha"]
    assert final_line is not None
    assert final_line.text == "beta"
