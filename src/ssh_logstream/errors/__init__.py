"""
ssh_logstream.errors
====================

Public error exports for ssh-logstream.
"""

from ssh_logstream.errors.exceptions import (
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

__all__ = [
    "AuthenticationError",
    "ConfigurationError",
    "DecodeError",
    "LineTooLongError",
    "RemoteFileAmbiguityError",
    "RemoteFileNotFoundError",
    "SshConnectionError",
    "SshLogStreamError",
    "StreamingError",
]
