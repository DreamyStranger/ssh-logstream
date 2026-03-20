"""
ssh_logstream.config.ssh
========================

SSH connection configuration models.

Overview
--------
This module defines the validated `SshConfig` dataclass used by the transport
layer.

Validation guarantees
---------------------
- `host` is present and non-empty
- `port` is a valid TCP port
- at least one of `private_key_path` or `password` is provided
- timeout and keepalive values are within supported ranges
- user-supplied paths are normalized with home-directory expansion
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ssh_logstream.errors import ConfigurationError


def _require_non_empty(value: str | None, *, field_name: str) -> str:
    if value is None:
        raise ConfigurationError(f"{field_name} must be provided.")
    normalized = value.strip()
    if not normalized:
        raise ConfigurationError(f"{field_name} must not be empty.")
    return normalized


def _expand_optional_path(path: str | None) -> str | None:
    if path is None:
        return None
    return str(Path(path).expanduser())


@dataclass(frozen=True, slots=True)
class SshConfig:
    """Validated SSH connection settings."""

    host: str
    port: int = 22
    username: str | None = None
    private_key_path: str | None = None
    password: str | None = None
    connect_timeout_seconds: float = 30.0
    keepalive_seconds: int = 10
    known_hosts_path: str | None = None
    allow_unknown_hosts: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "host", _require_non_empty(self.host, field_name="host"))
        if not 1 <= self.port <= 65535:
            raise ConfigurationError("port must be between 1 and 65535.")
        if self.username is not None:
            object.__setattr__(
                self,
                "username",
                _require_non_empty(self.username, field_name="username"),
            )
        object.__setattr__(self, "private_key_path", _expand_optional_path(self.private_key_path))
        object.__setattr__(self, "known_hosts_path", _expand_optional_path(self.known_hosts_path))
        if self.private_key_path is None and self.password is None:
            raise ConfigurationError(
                "At least one of private_key_path or password must be provided."
            )
        if self.connect_timeout_seconds <= 0:
            raise ConfigurationError("connect_timeout_seconds must be positive.")
        if self.keepalive_seconds < 0:
            raise ConfigurationError("keepalive_seconds must be greater than or equal to 0.")
