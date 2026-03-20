"""
ssh_logstream.models.resolved_file
==================================

Structured model for resolved remote files.

Overview
--------
This module defines `ResolvedFile`, the immutable result of remote file
selection prior to byte streaming.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResolvedFile:
    """A deterministically resolved remote file path."""

    folder: str
    filename: str
    path: str
