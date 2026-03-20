"""Unit tests for deterministic remote file resolution."""

from __future__ import annotations

import pytest

from ssh_logstream.errors import RemoteFileAmbiguityError, RemoteFileNotFoundError
from ssh_logstream.resolver import RemoteFileResolver, resolve_remote_member


class _FakeTransport:
    """Minimal fake transport for resolver tests."""

    def __init__(self, output: str) -> None:
        self._output = output

    def connect(self) -> None:
        return None

    def execute_text(self, command: str) -> str:
        assert "find " in command
        return self._output

    def open_stream(self, command: str) -> None:
        raise AssertionError(f"open_stream should not be called: {command}")

    def close(self) -> None:
        return None


def test_resolver_returns_single_match() -> None:
    resolver = RemoteFileResolver(_FakeTransport("/var/log/myapp/app.log\x00"))

    match = resolver.resolve(folder="/var/log/myapp", filename="app.log")

    assert match.path == "/var/log/myapp/app.log"


def test_resolver_raises_when_no_match_exists() -> None:
    resolver = RemoteFileResolver(_FakeTransport(""))

    with pytest.raises(RemoteFileNotFoundError):
        resolver.resolve(folder="/var/log/myapp", filename="app.log")


def test_resolver_raises_when_multiple_matches_exist() -> None:
    output = "/var/log/myapp/app.log\x00/var/log/myapp/archive/app.log\x00"
    resolver = RemoteFileResolver(_FakeTransport(output))

    with pytest.raises(RemoteFileAmbiguityError, match="Multiple remote files"):
        resolver.resolve(folder="/var/log/myapp", filename="app.log")


def test_resolver_matches_literal_filename_not_glob_pattern() -> None:
    output = "/var/log/myapp/app[1].log\x00/var/log/myapp/app1.log\x00"
    resolver = RemoteFileResolver(_FakeTransport(output))

    match = resolver.resolve(folder="/var/log/myapp", filename="app[1].log")

    assert match.path == "/var/log/myapp/app[1].log"


def test_member_resolution_prefers_exact_basename_matches() -> None:
    candidates = [
        "/var/log/myapp/service-a/app.log",
        "/var/log/myapp/archive/service-a/app.log",
        "/var/log/myapp/service-b/other.log",
    ]

    matches = resolve_remote_member(candidates, "app.log")

    assert matches == [
        "/var/log/myapp/service-a/app.log",
        "/var/log/myapp/archive/service-a/app.log",
    ]


def test_member_resolution_falls_back_to_suffix_matching() -> None:
    candidates = [
        "/var/log/myapp/service-a/app.log.1",
        "/var/log/myapp/archive/service-a/app.log",
        "/var/log/myapp/service-b/app.log.2",
    ]

    matches = resolve_remote_member(candidates, "service-a/app.log")

    assert matches == ["/var/log/myapp/archive/service-a/app.log"]


def test_member_resolution_raises_ambiguity_for_suffix_matches() -> None:
    output = (
        "/var/log/myapp/archive/service-a/app.log\x00"
        "/var/log/myapp/backup/service-a/app.log\x00"
    )
    resolver = RemoteFileResolver(_FakeTransport(output))

    with pytest.raises(RemoteFileAmbiguityError):
        resolver.resolve(folder="/var/log/myapp", filename="service-a/app.log")
