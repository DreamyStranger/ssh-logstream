"""
ssh_logstream.config.streamer
=============================

Streaming configuration models.

Overview
--------
This module defines `LineStreamerConfig`, the validated configuration object
that controls chunking, decoding, and partial-line buffering.

Bounded-memory contract
-----------------------
- `chunk_size` controls the maximum transport read size
- `max_line_bytes` caps the in-progress partial-line buffer
- codec settings are validated eagerly before streaming begins
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass

from ssh_logstream.errors import ConfigurationError

# Byte sequences that indicate a BOM is unconditionally prepended by the codec.
_BOM_PREFIXES = (
    b"\xff\xfe",  # UTF-16-LE BOM / UTF-32-LE BOM (first two bytes)
    b"\xfe\xff",  # UTF-16-BE BOM
    b"\x00\x00\xfe\xff",  # UTF-32-BE BOM (superset check done by startswith)
    b"\xef\xbb\xbf",  # UTF-8-SIG BOM
)


def _is_ascii_compatible(encoding: str) -> bool:
    """Return True if ASCII bytes round-trip unchanged for this codec.

    Non-ASCII-compatible encodings (e.g. UTF-16-LE) use a multi-byte
    representation even for code points below 128, so byte-level newline
    scanning and suffix-encoding arithmetic have stricter constraints.
    """
    try:
        return "A".encode(encoding) == b"A"
    except (LookupError, UnicodeEncodeError):
        return False


def _encoding_injects_bom(encoding: str) -> bool:
    """Return True if *encoding* unconditionally prepends a BOM to every encode call.

    BOM-injecting codecs (``utf-16``, ``utf-32``, ``utf-8-sig``) break the
    suffix-encoding arithmetic used by ``_find_raw_prefix_length`` because the
    extra BOM bytes make the encoded suffix longer than its raw counterpart in
    the stream.
    """
    try:
        sample = "A".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return any(sample.startswith(bom) for bom in _BOM_PREFIXES)


@dataclass(frozen=True, slots=True)
class LineStreamerConfig:
    """Streaming limits that enforce bounded-memory line iteration."""

    chunk_size: int = 64 * 1024
    encoding: str = "utf-8"
    errors: str = "strict"
    max_line_bytes: int = 8 * (1 << 20)

    def __post_init__(self) -> None:
        if self.chunk_size <= 0:
            raise ConfigurationError("chunk_size must be positive.")
        if self.max_line_bytes <= 0:
            raise ConfigurationError("max_line_bytes must be positive.")
        if self.max_line_bytes < self.chunk_size:
            raise ConfigurationError("max_line_bytes must be greater than or equal to chunk_size.")
        try:
            codecs.lookup(self.encoding)
        except LookupError as exc:
            raise ConfigurationError(f"Unsupported encoding: {self.encoding!r}.") from exc
        try:
            codecs.lookup_error(self.errors)
        except LookupError as exc:
            raise ConfigurationError(f"Unsupported decode error handler: {self.errors!r}.") from exc
        if _encoding_injects_bom(self.encoding):
            raise ConfigurationError(
                f"Encoding {self.encoding!r} injects a byte-order mark (BOM) on every encode call, "
                "which breaks cross-chunk boundary detection.  "
                "Use the explicit byte-order variant instead "
                "(e.g. 'utf-16-le', 'utf-16-be', 'utf-32-le', 'utf-32-be')."
            )
        if self.errors == "ignore" and not _is_ascii_compatible(self.encoding):
            raise ConfigurationError(
                f"errors='ignore' is not supported with non-ASCII-compatible encoding "
                f"{self.encoding!r}.  "
                "Silently dropped bytes break the raw-byte boundary arithmetic used "
                "during line splitting.  Use errors='replace' or errors='strict' instead."
            )
