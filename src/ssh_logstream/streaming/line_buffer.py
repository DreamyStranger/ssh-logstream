"""
ssh_logstream.streaming.line_buffer
===================================

Bounded line buffer for incremental streaming.

Overview
--------
This module holds the in-progress portion of the remote stream and emits
complete logical lines as soon as they can be resolved.

Performance model
-----------------
Most production logs use ASCII-compatible encodings such as UTF-8, Latin-1, or
Windows code pages. For those encodings, this module uses a raw-byte fast path
that finds newline boundaries directly in the undecided byte buffer. That keeps
the common case linear in the amount of streamed data.

For non-ASCII-compatible encodings such as UTF-16, the module falls back to a
generic decoded-text path that preserves correctness across chunk boundaries.

Responsibilities
----------------
- retain only the undecided raw bytes and decoded text fragments
- normalize CRLF-style endings for emitted lines
- enforce `max_line_bytes` on the current partial line
- preserve encoding-correct behavior for non-ASCII-compatible codecs
"""

from __future__ import annotations

import codecs
import functools
from collections import deque
from collections.abc import Iterator

from ssh_logstream.errors import DecodeError, LineTooLongError
from ssh_logstream.models import LineRecord


@functools.cache
def _is_ascii_compatible_encoding(encoding: str) -> bool:
    """Return whether ASCII bytes round-trip unchanged for this codec."""

    try:
        for char_code in range(128):
            character = chr(char_code)
            encoded = character.encode(encoding)
            if encoded != bytes([char_code]):
                return False
        return True
    except UnicodeError:
        return False
    except LookupError:
        return False


class LineBuffer:
    """Store partial raw bytes while splitting lines with bounded memory."""

    def __init__(self, *, encoding: str, errors: str, max_line_bytes: int) -> None:
        self._encoding = encoding
        self._errors = errors
        self._max_line_bytes = max_line_bytes
        self._ascii_compatible = _is_ascii_compatible_encoding(encoding)

        self._raw_buffer = bytearray()
        self._raw_start = 0
        self._buffered_bytes = 0

        self._decoded_buffer = ""
        self._raw_segments: deque[tuple[bytes, str]] = deque()

    def append_chunk(self, chunk: bytes, *, decoded_text: str) -> None:
        """Append raw bytes plus their decoded text contribution."""

        if not chunk and not decoded_text:
            return

        self._raw_buffer.extend(chunk)
        self._buffered_bytes += len(chunk)

        if not self._ascii_compatible:
            self._decoded_buffer += decoded_text
            self._raw_segments.append((chunk, decoded_text))

    @property
    def requires_decoded_chunks(self) -> bool:
        """Return whether this buffer needs decoded chunk text from the caller."""

        return not self._ascii_compatible

    def pop_lines(self) -> Iterator[LineRecord]:
        """Yield complete lines and retain only the trailing partial line."""

        if self._ascii_compatible:
            yield from self._pop_lines_ascii_compatible()
            return

        yield from self._pop_lines_generic()

    def pop_text_lines(self) -> Iterator[str]:
        """Yield complete decoded lines without allocating `LineRecord` objects."""

        if self._ascii_compatible:
            yield from self._pop_text_lines_ascii_compatible()
            return

        yield from self._pop_text_lines_generic()

    def pop_final_line(self) -> LineRecord | None:
        """Emit the remaining partial line at end-of-stream."""

        if self._buffered_bytes == 0:
            return None

        raw_line = bytes(memoryview(self._raw_buffer)[self._raw_start :])
        byte_length = self._buffered_bytes
        self._raw_buffer.clear()
        self._raw_start = 0
        self._buffered_bytes = 0

        if self._ascii_compatible:
            text = self._decode_line(raw_line)
            return LineRecord(text=self._normalize_line(text), byte_length=byte_length)

        decoded_text = self._decoded_buffer
        self._decoded_buffer = ""
        self._raw_segments.clear()
        if raw_line and not decoded_text:
            decoded_text = self._decode_line(raw_line)
        return LineRecord(text=self._normalize_line(decoded_text), byte_length=byte_length)

    def pop_final_text(self) -> str | None:
        """Emit the remaining partial line text at end-of-stream."""

        if self._buffered_bytes == 0:
            return None

        if self._ascii_compatible:
            text = self._normalize_line(
                self._decode_line(memoryview(self._raw_buffer)[self._raw_start :])
            )
            self._raw_buffer.clear()
            self._raw_start = 0
            self._buffered_bytes = 0
            return text

        decoded_text = self._decoded_buffer
        if self._buffered_bytes > 0 and not decoded_text:
            decoded_text = self._decode_line(memoryview(self._raw_buffer)[self._raw_start :])
        self._raw_buffer.clear()
        self._raw_start = 0
        self._buffered_bytes = 0
        self._decoded_buffer = ""
        self._raw_segments.clear()
        return self._normalize_line(decoded_text)

    def ensure_limit(self) -> None:
        """Raise when the current partial line exceeds the configured byte ceiling."""

        if self._buffered_bytes > self._max_line_bytes:
            raise LineTooLongError(
                "Buffered partial line exceeded max_line_bytes while streaming."
            )

    def _pop_lines_ascii_compatible(self) -> Iterator[LineRecord]:
        while True:
            raw_newline_index = self._raw_buffer.find(b"\n", self._raw_start)
            if raw_newline_index < 0:
                self._compact_raw_buffer()
                return

            consumed = raw_newline_index + 1 - self._raw_start
            line_text = self._decode_line(
                memoryview(self._raw_buffer)[self._raw_start : raw_newline_index]
            )
            self._raw_start = raw_newline_index + 1
            self._buffered_bytes -= consumed

            yield LineRecord(text=self._normalize_line(line_text), byte_length=consumed)

    def _pop_text_lines_ascii_compatible(self) -> Iterator[str]:
        while True:
            raw_newline_index = self._raw_buffer.find(b"\n", self._raw_start)
            if raw_newline_index < 0:
                self._compact_raw_buffer()
                return

            consumed = raw_newline_index + 1 - self._raw_start
            line_text = self._decode_line(
                memoryview(self._raw_buffer)[self._raw_start : raw_newline_index]
            )
            self._raw_start = raw_newline_index + 1
            self._buffered_bytes -= consumed

            yield self._normalize_line(line_text)

    def _pop_lines_generic(self) -> Iterator[LineRecord]:
        while True:
            newline_index = self._decoded_buffer.find("\n")
            if newline_index < 0:
                return

            line_with_newline = self._decoded_buffer[: newline_index + 1]
            consumed_bytes = self._consume_decoded_prefix(line_with_newline)
            self._decoded_buffer = self._decoded_buffer[newline_index + 1 :]
            line_text = line_with_newline[:-1]
            yield LineRecord(
                text=self._normalize_line(line_text),
                byte_length=consumed_bytes,
            )

    def _pop_text_lines_generic(self) -> Iterator[str]:
        while True:
            newline_index = self._decoded_buffer.find("\n")
            if newline_index < 0:
                return

            line_with_newline = self._decoded_buffer[: newline_index + 1]
            self._consume_decoded_prefix(line_with_newline)
            self._decoded_buffer = self._decoded_buffer[newline_index + 1 :]
            yield self._normalize_line(line_with_newline[:-1])

    def _consume_decoded_prefix(self, target_text: str) -> int:
        consumed_bytes = 0
        remaining = target_text

        while remaining:
            if not self._raw_segments:
                raise DecodeError("Unable to map decoded line boundaries back to raw bytes.")

            raw_chunk, decoded_text = self._raw_segments[0]
            if not decoded_text:
                self._raw_segments.popleft()
                consumed_bytes += len(raw_chunk)
                self._consume_raw_bytes(len(raw_chunk))
                continue

            if remaining.startswith(decoded_text):
                self._raw_segments.popleft()
                consumed_bytes += len(raw_chunk)
                self._consume_raw_bytes(len(raw_chunk))
                remaining = remaining[len(decoded_text) :]
                continue

            prefix_chars = len(remaining)
            prefix_bytes = self._find_raw_prefix_length(raw_chunk, decoded_text, remaining)
            consumed_bytes += prefix_bytes
            self._consume_raw_bytes(prefix_bytes)
            remaining = remaining[prefix_chars:]

            suffix_raw = raw_chunk[prefix_bytes:]
            suffix_text = decoded_text[prefix_chars:]
            self._raw_segments[0] = (suffix_raw, suffix_text)

        return consumed_bytes

    def _consume_raw_bytes(self, count: int) -> None:
        if count <= 0:
            return
        self._raw_start += count
        self._buffered_bytes -= count
        self._compact_raw_buffer()

    def _compact_raw_buffer(self) -> None:
        if self._raw_start == 0:
            return
        if self._buffered_bytes == 0:
            self._raw_buffer.clear()
            self._raw_start = 0
            return
        if self._raw_start < len(self._raw_buffer) // 2:
            return
        del self._raw_buffer[: self._raw_start]
        self._raw_start = 0

    def _find_raw_prefix_length(
        self, raw_chunk: bytes, decoded_text: str, target_text: str
    ) -> int:
        """Return how many bytes of raw_chunk correspond to target_text.

        target_text must be a prefix of decoded_text.  The byte boundary is
        found by encoding the suffix (decoded_text[len(target_text):]) with the
        configured codec and subtracting its byte length from len(raw_chunk).
        This avoids creating a fresh incremental decoder, which would be wrong
        when raw_chunk starts with carry-over bytes from the previous chunk.
        """
        suffix = decoded_text[len(target_text) :]
        try:
            encoded_suffix = suffix.encode(self._encoding)
        except UnicodeError as exc:
            raise DecodeError("Unable to map decoded line boundaries back to raw bytes.") from exc
        prefix_bytes = len(raw_chunk) - len(encoded_suffix)
        if prefix_bytes < 0 or raw_chunk[prefix_bytes:] != encoded_suffix:
            raise DecodeError("Unable to map decoded line boundaries back to raw bytes.")
        return prefix_bytes

    def _decode_line(self, raw_line: bytes | memoryview) -> str:
        try:
            return codecs.decode(raw_line, self._encoding, errors=self._errors)
        except UnicodeError as exc:
            raise DecodeError("Failed to decode streamed remote bytes.") from exc

    def _normalize_line(self, line: str) -> str:
        if line.endswith("\r"):
            return line[:-1]
        return line
