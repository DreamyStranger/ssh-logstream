"""
ssh_logstream.streaming.line_streamer_core
==========================================

Core byte-to-line streaming pipeline.

Overview
--------
This module coordinates incremental decoding and bounded line buffering to turn
a byte-chunk iterator into an iterator of decoded line records.

Design goals
------------
- keep orchestration outside of transport and client layers
- centralize bounded-memory line emission logic
- remain parser-agnostic by yielding decoded text only
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from ssh_logstream.config import LineStreamerConfig
from ssh_logstream.models import LineRecord
from ssh_logstream.streaming.decoder import IncrementalDecoder
from ssh_logstream.streaming.line_buffer import LineBuffer


class LineStreamerCore:
    """Turn raw byte chunks into normalized line records with bounded memory."""

    def __init__(self, config: LineStreamerConfig) -> None:
        self._buffer = LineBuffer(
            encoding=config.encoding,
            errors=config.errors,
            max_line_bytes=config.max_line_bytes,
        )
        self._decoder = (
            IncrementalDecoder(encoding=config.encoding, errors=config.errors)
            if self._buffer.requires_decoded_chunks
            else None
        )

    def iter_lines(self, chunks: Iterable[bytes]) -> Iterator[LineRecord]:
        """Yield line records from a byte stream."""

        for chunk in chunks:
            decoded_text = self._decode_chunk(chunk)
            self._buffer.append_chunk(chunk, decoded_text=decoded_text)
            yield from self._buffer.pop_lines()
            self._buffer.ensure_limit()
        tail = self._flush_decoder()
        self._buffer.append_chunk(b"", decoded_text=tail)
        final_line = self._buffer.pop_final_line()
        if final_line is not None:
            yield final_line

    def iter_text(self, chunks: Iterable[bytes]) -> Iterator[str]:
        """Yield normalized decoded lines without allocating `LineRecord` objects."""

        for chunk in chunks:
            decoded_text = self._decode_chunk(chunk)
            self._buffer.append_chunk(chunk, decoded_text=decoded_text)
            yield from self._buffer.pop_text_lines()
            self._buffer.ensure_limit()
        tail = self._flush_decoder()
        self._buffer.append_chunk(b"", decoded_text=tail)
        final_text = self._buffer.pop_final_text()
        if final_text is not None:
            yield final_text

    def _decode_chunk(self, chunk: bytes) -> str:
        if self._decoder is None:
            return ""
        return self._decoder.decode_chunk(chunk)

    def _flush_decoder(self) -> str:
        if self._decoder is None:
            return ""
        return self._decoder.flush()
