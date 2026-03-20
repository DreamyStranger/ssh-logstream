"""
ssh_logstream.models.line_record
================================

Structured line model for internal streaming stages.

Overview
--------
This module defines `LineRecord`, an immutable value object used inside the
streaming pipeline to pair emitted text with its raw-byte length.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LineRecord:
    """A decoded text line with its raw byte length."""

    text: str
    byte_length: int
