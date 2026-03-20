"""Unit tests for incremental byte decoding."""

from __future__ import annotations

import pytest

from ssh_logstream import DecodeError
from ssh_logstream.streaming import IncrementalDecoder


def test_incremental_decoder_handles_chunk_boundaries() -> None:
    decoder = IncrementalDecoder(encoding="utf-8", errors="strict")

    first = decoder.decode_chunk(b"caf")
    second = decoder.decode_chunk(b"\xc3\xa9\n")

    assert first == "caf"
    assert second == "\u00e9\n"


def test_incremental_decoder_wraps_decode_errors() -> None:
    decoder = IncrementalDecoder(encoding="utf-8", errors="strict")

    with pytest.raises(DecodeError):
        decoder.decode_chunk(b"\xff")
