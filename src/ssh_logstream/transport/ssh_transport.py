"""
ssh_logstream.transport.ssh_transport
=====================================

SSH transport abstractions and Paramiko-backed implementation.

Overview
--------
This module isolates SSH-specific behavior behind a small transport surface
used by the rest of the library.

Responsibilities
----------------
- establish authenticated SSH connections
- execute short-lived remote text commands
- expose long-running remote stdout streams as chunk iterators
- map Paramiko and network failures into library-specific exceptions

Design goals
------------
- Keep SSH details out of public orchestration code
- Provide a narrow interface that is easy to fake in tests
- Preserve bounded-memory behavior while streaming large remote files
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Protocol

log = logging.getLogger(__name__)

import paramiko
from paramiko.ssh_exception import (
    AuthenticationException,
    BadHostKeyException,
    NoValidConnectionsError,
    SSHException,
)

from ssh_logstream.config import SshConfig
from ssh_logstream.errors import AuthenticationError, SshConnectionError, StreamingError


def _append_limited(buffer: bytearray, data: bytes, *, limit: int) -> None:
    """Keep only the most recent bytes from a potentially unbounded stderr stream."""

    if not data:
        return
    buffer.extend(data)
    if len(buffer) > limit:
        del buffer[:-limit]


def _read_command_output(
    channel: paramiko.Channel, *, chunk_size: int = 64 * 1024
) -> tuple[bytes, bytes]:
    """Drain stdout and stderr fully before reading the command exit status."""

    stdout_buffer = bytearray()
    stderr_buffer = bytearray()

    while True:
        while channel.recv_ready():
            stdout_buffer.extend(channel.recv(chunk_size))
        while channel.recv_stderr_ready():
            stderr_buffer.extend(channel.recv_stderr(chunk_size))
        exited = channel.exit_status_ready()
        if exited and not channel.recv_ready() and not channel.recv_stderr_ready():
            break
        time.sleep(0.005)
    return bytes(stdout_buffer), bytes(stderr_buffer)


class RemoteCommandStream(AbstractContextManager["RemoteCommandStream"], Protocol):
    """A context-managed byte stream for a running remote command."""

    def iter_chunks(self, chunk_size: int) -> Iterator[bytes]:
        """Yield raw byte chunks from the remote command output."""

    def close(self) -> None:
        """Release command resources."""


class SshTransport(Protocol):
    """Protocol for SSH operations needed by the library."""

    def connect(self) -> None:
        """Establish any underlying SSH resources."""

    def execute_text(self, command: str) -> str:
        """Run a command and return decoded stdout text."""

    def open_stream(self, command: str) -> RemoteCommandStream:
        """Open a remote command as a raw byte stream."""

    def close(self) -> None:
        """Release the underlying SSH resources."""


class _ParamikoCommandStream(RemoteCommandStream):
    """Wrap a Paramiko channel as an iterator over stdout bytes."""

    def __init__(self, client: paramiko.SSHClient, command: str) -> None:
        transport = client.get_transport()
        if transport is None:
            raise SshConnectionError("SSH transport is not available.")
        self._channel = transport.open_session()
        self._stderr_buffer = bytearray()
        self._channel.exec_command(command)
        log.debug("stream channel opened")

    def __enter__(self) -> _ParamikoCommandStream:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def iter_chunks(self, chunk_size: int) -> Iterator[bytes]:
        """Yield stdout bytes until the remote command ends."""

        try:
            while True:
                while self._channel.recv_stderr_ready():
                    _append_limited(
                        self._stderr_buffer,
                        self._channel.recv_stderr(chunk_size),
                        limit=64 * 1024,
                    )
                if self._channel.recv_ready():
                    data = self._channel.recv(chunk_size)
                    if data:
                        yield data
                        continue
                if self._channel.exit_status_ready():
                    while self._channel.recv_stderr_ready():
                        _append_limited(
                            self._stderr_buffer,
                            self._channel.recv_stderr(chunk_size),
                            limit=64 * 1024,
                        )
                    while self._channel.recv_ready():
                        data = self._channel.recv(chunk_size)
                        if data:
                            yield data
                    exit_status = self._channel.recv_exit_status()
                    if exit_status != 0:
                        message = (
                            bytes(self._stderr_buffer).decode("utf-8", errors="replace").strip()
                        )
                        detail = message or f"remote command exited with status {exit_status}"
                        log.warning("remote command exited with non-zero status %d", exit_status)
                        raise StreamingError(detail)
                    log.debug("stream channel closed cleanly")
                    return
                self._channel.settimeout(1.0)
                try:
                    data = self._channel.recv(chunk_size)
                except TimeoutError:
                    continue
                finally:
                    self._channel.settimeout(None)
                if data:
                    yield data
        except SSHException as exc:
            log.error("SSH channel failed while streaming: %s", exc)
            raise SshConnectionError("SSH channel failed while streaming remote data.") from exc

    def close(self) -> None:
        """Close the underlying Paramiko channel."""

        self._channel.close()


class ParamikoSshTransport(SshTransport):
    """SSH transport that delegates to Paramiko for connections and channels."""

    def __init__(self, ssh_config: SshConfig) -> None:
        self._ssh_config = ssh_config
        self._client = paramiko.SSHClient()
        if ssh_config.known_hosts_path is not None:
            self._client.load_host_keys(ssh_config.known_hosts_path)
        else:
            self._client.load_system_host_keys()
        if ssh_config.allow_unknown_hosts:
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        else:
            self._client.set_missing_host_key_policy(paramiko.RejectPolicy())
        self._connected = False

    def connect(self) -> None:
        """Connect to the remote host with strict error mapping."""

        if self._connected:
            return
        log.debug(
            "connecting to %s:%d (user=%r)",
            self._ssh_config.host,
            self._ssh_config.port,
            self._ssh_config.username,
        )
        try:
            self._client.connect(
                hostname=self._ssh_config.host,
                port=self._ssh_config.port,
                username=self._ssh_config.username,
                key_filename=self._ssh_config.private_key_path,
                password=self._ssh_config.password,
                timeout=self._ssh_config.connect_timeout_seconds,
                banner_timeout=self._ssh_config.connect_timeout_seconds,
                auth_timeout=self._ssh_config.connect_timeout_seconds,
                look_for_keys=False,
                allow_agent=False,
            )
            transport = self._client.get_transport()
            if transport is not None:
                transport.set_keepalive(self._ssh_config.keepalive_seconds)
            self._connected = True
            log.debug("connected to %s:%d", self._ssh_config.host, self._ssh_config.port)
        except AuthenticationException as exc:
            log.error(
                "authentication failed for %s:%d (user=%r)",
                self._ssh_config.host,
                self._ssh_config.port,
                self._ssh_config.username,
            )
            raise AuthenticationError("SSH authentication failed.") from exc
        except (TimeoutError, BadHostKeyException, NoValidConnectionsError, SSHException) as exc:
            log.error(
                "connection failed to %s:%d: %s",
                self._ssh_config.host,
                self._ssh_config.port,
                exc,
            )
            raise SshConnectionError("Unable to establish SSH connection.") from exc

    def execute_text(self, command: str) -> str:
        """Run a command and decode its stdout as UTF-8 control text."""

        self.connect()
        try:
            _, stdout, _stderr = self._client.exec_command(command)
            channel = stdout.channel
            output_bytes, error_bytes = _read_command_output(channel)
            exit_status = channel.recv_exit_status()
            output = output_bytes.decode("utf-8", errors="replace")
            error_output = error_bytes.decode("utf-8", errors="replace").strip()
        except SSHException as exc:
            raise SshConnectionError("SSH command execution failed.") from exc
        if exit_status != 0:
            detail = error_output or f"remote command exited with status {exit_status}"
            raise StreamingError(detail)
        return output

    def open_stream(self, command: str) -> RemoteCommandStream:
        """Open a raw stdout byte stream for a long-running remote command."""

        self.connect()
        return _ParamikoCommandStream(self._client, command)

    def close(self) -> None:
        """Close the Paramiko client."""

        self._client.close()
        self._connected = False
        log.debug("disconnected from %s:%d", self._ssh_config.host, self._ssh_config.port)
