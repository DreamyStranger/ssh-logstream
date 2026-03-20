"""
ssh_logstream
=============

Public package exports for ssh-logstream.

Overview
--------
This package exposes the small public surface of the library:
- `__version__`
- `LineStreamer`
- `SshConfig`
- `LineStreamerConfig`
- `StreamStats`
- the documented exception hierarchy
"""

from ssh_logstream.client import LineStreamer
from ssh_logstream.config import LineStreamerConfig, SshConfig
from ssh_logstream.errors import (
    AuthenticationError,
    ConfigurationError,
    DecodeError,
    LineTooLongError,
    RemoteFileAmbiguityError,
    RemoteFileNotFoundError,
    SshConnectionError,
    SshLogStreamError,
    StreamingError,
)
from ssh_logstream.models import StreamStats
from ssh_logstream.version import __version__

__all__ = [
    "AuthenticationError",
    "ConfigurationError",
    "DecodeError",
    "LineStreamer",
    "LineStreamerConfig",
    "LineTooLongError",
    "RemoteFileAmbiguityError",
    "RemoteFileNotFoundError",
    "SshConfig",
    "SshConnectionError",
    "SshLogStreamError",
    "StreamStats",
    "StreamingError",
    "__version__",
]
