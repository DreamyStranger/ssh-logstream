"""
ssh_logstream.models.stream_stats
==================================

Streaming session counters.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class StreamStats:
    """Live counters accumulated during a single streaming session.

    The object is created fresh when a new ``stream()`` iterator begins
    producing values and updated in-place as iteration progresses. It remains
    readable after the generator is exhausted or the caller breaks out of the
    loop.

    Fields
    ------
    bytes_read:
        Total raw bytes received from the SSH channel for this session.
        Divide by elapsed wall time to get throughput.
    chunks_read:
        Number of SSH read calls issued.  A very high value relative to
        ``bytes_read`` indicates that ``chunk_size`` is too small.
    lines_emitted:
        Total complete lines yielded to the caller, including the final
        partial line at EOF.
    """

    bytes_read: int = 0
    chunks_read: int = 0
    lines_emitted: int = 0
