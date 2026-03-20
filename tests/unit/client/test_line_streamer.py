"""Unit tests for the high-level LineStreamer API."""

from __future__ import annotations

from collections.abc import Iterator
from types import TracebackType

import pytest

from ssh_logstream import LineStreamer, LineStreamerConfig, SshConfig, StreamStats
from ssh_logstream.client.line_streamer import LineStreamer as InternalLineStreamer
from ssh_logstream.errors import RemoteFileNotFoundError


class _FakeCommandStream:
    """Context-managed stream for deterministic byte chunks."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.closed = False

    def __enter__(self) -> _FakeCommandStream:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def iter_chunks(self, chunk_size: int) -> Iterator[bytes]:
        assert chunk_size > 0
        yield from self._chunks

    def close(self) -> None:
        self.closed = True


class _FakeTransport:
    """Fake SSH transport for high-level API tests."""

    def __init__(self, *, resolver_output: str, stream_chunks: list[bytes]) -> None:
        self._resolver_output = resolver_output
        self._stream_chunks = stream_chunks
        self.connected = False
        self.closed = False
        self.commands: list[str] = []

    def connect(self) -> None:
        self.connected = True

    def execute_text(self, command: str) -> str:
        self.commands.append(command)
        return self._resolver_output

    def open_stream(self, command: str) -> _FakeCommandStream:
        self.commands.append(command)
        return _FakeCommandStream(self._stream_chunks)

    def close(self) -> None:
        self.closed = True
def test_readme_primary_usage_example(monkeypatch, ssh_config: SshConfig) -> None:
    config = LineStreamerConfig(
        chunk_size=1 << 20,
        encoding="utf-8",
        errors="replace",
        max_line_bytes=32 * (1 << 20),
    )
    fake_transport = _FakeTransport(
        resolver_output="/var/log/myapp/app.log\x00",
        stream_chunks=[b"line one\nline two\n"],
    )

    monkeypatch.setattr(InternalLineStreamer, "_build_transport", lambda self: fake_transport)

    streamer = LineStreamer(
        folder="/var/log/myapp",
        filename="app.log",
        ssh_config=ssh_config,
        config=config,
    )

    assert list(streamer.stream()) == ["line one", "line two"]
    assert fake_transport.connected is True
    assert fake_transport.closed is True


def test_line_streamer_supports_follow_mode(monkeypatch, ssh_config: SshConfig) -> None:
    fake_transport = _FakeTransport(
        resolver_output="/var/log/myapp/app.log\x00",
        stream_chunks=[b"first\n", b"second\n"],
    )
    monkeypatch.setattr(InternalLineStreamer, "_build_transport", lambda self: fake_transport)

    streamer = LineStreamer(
        folder="/var/log/myapp",
        filename="app.log",
        ssh_config=ssh_config,
    )

    assert list(streamer.stream(follow=True)) == ["first", "second"]
    assert any("tail -n +1 -F" in command for command in fake_transport.commands)


def test_line_streamer_emits_final_partial_line(monkeypatch, ssh_config: SshConfig) -> None:
    fake_transport = _FakeTransport(
        resolver_output="/var/log/myapp/app.log\x00",
        stream_chunks=[b"partial line"],
    )
    monkeypatch.setattr(InternalLineStreamer, "_build_transport", lambda self: fake_transport)

    streamer = LineStreamer(
        folder="/var/log/myapp",
        filename="app.log",
        ssh_config=ssh_config,
    )

    assert list(streamer.stream()) == ["partial line"]


def test_line_streamer_stats_accumulate_correctly(monkeypatch, ssh_config: SshConfig) -> None:
    chunk_a = b"line one\nline two\n"
    chunk_b = b"partial"
    fake_transport = _FakeTransport(
        resolver_output="/var/log/myapp/app.log\x00",
        stream_chunks=[chunk_a, chunk_b],
    )
    monkeypatch.setattr(InternalLineStreamer, "_build_transport", lambda self: fake_transport)

    streamer = LineStreamer(
        folder="/var/log/myapp",
        filename="app.log",
        ssh_config=ssh_config,
    )

    assert isinstance(streamer.stats, StreamStats)
    assert streamer.stats.lines_emitted == 0

    lines = list(streamer.stream())

    assert lines == ["line one", "line two", "partial"]
    assert streamer.stats.bytes_read == len(chunk_a) + len(chunk_b)
    assert streamer.stats.chunks_read == 2
    assert streamer.stats.lines_emitted == 3


def test_line_streamer_stats_reset_on_each_stream_call(monkeypatch, ssh_config: SshConfig) -> None:
    fake_transport = _FakeTransport(
        resolver_output="/var/log/myapp/app.log\x00",
        stream_chunks=[b"a\nb\n"],
    )
    monkeypatch.setattr(InternalLineStreamer, "_build_transport", lambda self: fake_transport)

    streamer = LineStreamer(
        folder="/var/log/myapp",
        filename="app.log",
        ssh_config=ssh_config,
    )

    list(streamer.stream())
    first_lines = streamer.stats.lines_emitted

    list(streamer.stream())
    assert streamer.stats.lines_emitted == first_lines


def test_line_streamer_closes_transport_on_resolution_error(
    monkeypatch, ssh_config: SshConfig
) -> None:
    fake_transport = _FakeTransport(resolver_output="", stream_chunks=[])
    monkeypatch.setattr(InternalLineStreamer, "_build_transport", lambda self: fake_transport)

    streamer = LineStreamer(
        folder="/var/log/myapp",
        filename="missing.log",
        ssh_config=ssh_config,
    )

    with pytest.raises(RemoteFileNotFoundError):
        list(streamer.stream())

    assert fake_transport.closed is True
