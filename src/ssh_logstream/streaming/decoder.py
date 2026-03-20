"""
ssh_logstream.streaming.decoder
===============================

Incremental byte-to-text decoding for remote streams.

Overview
--------
This module wraps Python's incremental codec machinery behind a small helper
used by the streaming pipeline.

Responsibilities
----------------
- decode chunked byte input without requiring whole-file buffering
- preserve codec state across chunk boundaries
- raise library-specific decode errors on failure
"""

from __future__ import annotations

import codecs

from ssh_logstream.errors import DecodeError


class IncrementalDecoder:
    """Decode streamed bytes incrementally using Python codecs."""

    def __init__(self, *, encoding: str, errors: str) -> None:
        self._decoder = codecs.getincrementaldecoder(encoding)(errors=errors)

    def decode_chunk(self, chunk: bytes) -> str:
        """Decode one streamed chunk."""

        try:
            return self._decoder.decode(chunk, final=False)
        except UnicodeError as exc:
            raise DecodeError("Failed to decode streamed remote bytes.") from exc

    def flush(self) -> str:
        """Flush any remaining decoder state."""

        try:
            return self._decoder.decode(b"", final=True)
        except UnicodeError as exc:
            raise DecodeError("Failed to decode the final remote byte sequence.") from exc
