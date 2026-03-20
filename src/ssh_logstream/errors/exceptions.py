"""
ssh_logstream.errors.exceptions
===============================

Structured exception hierarchy for ssh-logstream.

Overview
--------
This module defines the public error model for configuration, transport,
resolution, decoding, and bounded-streaming failures.

Design goals
------------
- precise operational failures
- stable top-level catch-all via `SshLogStreamError`
- clear separation between configuration, connection, and runtime errors
"""


class SshLogStreamError(Exception):
    """Base class for all library exceptions."""


class ConfigurationError(SshLogStreamError):
    """Raised when configuration is invalid before streaming begins."""


class AuthenticationError(SshLogStreamError):
    """Raised when SSH authentication fails."""


class SshConnectionError(SshLogStreamError):
    """Raised when an SSH connection cannot be established or maintained."""


class StreamingError(SshLogStreamError):
    """Raised when remote streaming fails for reasons other than decoding."""


class DecodeError(StreamingError):
    """Raised when streamed bytes cannot be decoded with the configured policy."""


class LineTooLongError(StreamingError):
    """Raised when the buffered partial line exceeds the configured byte limit."""


class RemoteFileNotFoundError(StreamingError):
    """Raised when the requested remote file cannot be found."""


class RemoteFileAmbiguityError(StreamingError):
    """Raised when file resolution returns more than one remote match."""
