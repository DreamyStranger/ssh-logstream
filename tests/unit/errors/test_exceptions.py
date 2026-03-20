"""Unit tests for exception hierarchy."""

from __future__ import annotations

from ssh_logstream.errors import (
    ConfigurationError,
    LineTooLongError,
    SshConnectionError,
    SshLogStreamError,
    StreamingError,
)


def test_exception_hierarchy_is_structured() -> None:
    assert issubclass(ConfigurationError, SshLogStreamError)
    assert issubclass(SshConnectionError, SshLogStreamError)
    assert issubclass(StreamingError, SshLogStreamError)
    assert issubclass(LineTooLongError, StreamingError)
