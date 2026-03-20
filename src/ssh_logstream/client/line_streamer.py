"""
ssh_logstream.client.line_streamer
=================================

High-level remote line streaming interface.

Overview
--------
This module provides the public `LineStreamer` class, which streams decoded
text lines from a remotely hosted file over SSH.

The class is intentionally orchestration-focused. It delegates:
- SSH configuration to `ssh_logstream.config`
- remote file selection to `ssh_logstream.resolver`
- command construction to `ssh_logstream.commands`
- bounded line emission to `ssh_logstream.streaming`

Public contract
---------------
- Remote files are streamed directly over SSH.
- Files are never copied to local disk.
- Decoded lines are yielded one at a time without trailing newlines.
- Memory remains bounded by chunked reads and partial-line buffering.

Design goals
------------
- Small and predictable public API
- Clear separation between transport, resolution, and streaming concerns
- Parser-agnostic output for downstream consumers
- Bounded-memory operation for very large inputs
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator

log = logging.getLogger(__name__)

from ssh_logstream.commands import build_follow_stream_command, build_snapshot_stream_command
from ssh_logstream.config import LineStreamerConfig, SshConfig
from ssh_logstream.errors import ConfigurationError
from ssh_logstream.models import StreamStats
from ssh_logstream.resolver import RemoteFileResolver
from ssh_logstream.streaming import LineStreamerCore
from ssh_logstream.transport import ParamikoSshTransport, SshTransport


def _require_non_empty(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ConfigurationError(f"{field_name} must not be empty.")
    return normalized


class LineStreamer:
    """Stream a remote text file line by line over SSH with bounded memory."""

    def __init__(
        self,
        *,
        folder: str,
        filename: str,
        ssh_config: SshConfig,
        config: LineStreamerConfig | None = None,
    ) -> None:
        self._folder = _require_non_empty(folder, field_name="folder")
        self._filename = _require_non_empty(filename, field_name="filename")
        self._ssh_config = ssh_config
        self._config = config or LineStreamerConfig()
        self._stats = StreamStats()

    @property
    def stats(self) -> StreamStats:
        """Live counters for the active or most recently completed stream session."""

        return self._stats

    def stream(self, *, follow: bool = False) -> Iterator[str]:
        """Yield decoded remote lines in snapshot mode or continuous follow mode."""

        self._stats = StreamStats()
        mode = "follow" if follow else "snapshot"
        log.debug("starting %s stream: folder=%r filename=%r", mode, self._folder, self._filename)
        transport = self._build_transport()
        try:
            transport.connect()
            resolved_file = RemoteFileResolver(transport).resolve(
                folder=self._folder,
                filename=self._filename,
            )
            command = (
                build_follow_stream_command(path=resolved_file.path)
                if follow
                else build_snapshot_stream_command(path=resolved_file.path)
            )
            core = LineStreamerCore(self._config)
            with transport.open_stream(command) as stream:
                chunks = self._counted_chunks(stream.iter_chunks(self._config.chunk_size))
                for line in core.iter_text(chunks):
                    self._stats.lines_emitted += 1
                    yield line
            log.debug(
                "stream complete: %d lines, %d bytes, %d chunks",
                self._stats.lines_emitted,
                self._stats.bytes_read,
                self._stats.chunks_read,
            )
        finally:
            transport.close()

    def _counted_chunks(self, chunks: Iterable[bytes]) -> Iterator[bytes]:
        """Yield chunks while accumulating byte and chunk-count stats."""

        for chunk in chunks:
            self._stats.bytes_read += len(chunk)
            self._stats.chunks_read += 1
            yield chunk

    def _build_transport(self) -> SshTransport:
        """Create the concrete SSH transport for this streamer."""

        return ParamikoSshTransport(self._ssh_config)
