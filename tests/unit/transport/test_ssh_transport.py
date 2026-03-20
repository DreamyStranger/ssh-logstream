"""Unit tests for transport helpers and module exports."""

from __future__ import annotations

import paramiko

from ssh_logstream import SshConfig
from ssh_logstream.transport import ParamikoSshTransport, RemoteCommandStream, SshTransport
from ssh_logstream.transport.ssh_transport import _read_command_output


def test_transport_exports_are_available() -> None:
    assert ParamikoSshTransport is not None
    assert RemoteCommandStream is not None
    assert SshTransport is not None


class _FakeChannel:
    """Minimal channel fake that simulates output buffering before process exit."""

    def __init__(self) -> None:
        self._stdout_chunks = [b"one", b"two"]
        self._stderr_chunks = [b"warn"]

    def recv_ready(self) -> bool:
        return bool(self._stdout_chunks)

    def recv_stderr_ready(self) -> bool:
        return bool(self._stderr_chunks)

    def recv(self, chunk_size: int) -> bytes:
        return self._stdout_chunks.pop(0)

    def recv_stderr(self, chunk_size: int) -> bytes:
        return self._stderr_chunks.pop(0)

    def exit_status_ready(self) -> bool:
        return not self._stdout_chunks and not self._stderr_chunks


def test_read_command_output_drains_stdout_and_stderr_before_exit_status() -> None:
    stdout_data, stderr_data = _read_command_output(_FakeChannel())  # type: ignore[arg-type]

    assert stdout_data == b"onetwo"
    assert stderr_data == b"warn"


class _FakeParamikoClient:
    """Small fake SSH client for transport-construction tests."""

    def __init__(self) -> None:
        self.policy = None
        self.loaded_host_keys = None
        self.loaded_system = False

    def load_host_keys(self, path: str) -> None:
        self.loaded_host_keys = path

    def load_system_host_keys(self) -> None:
        self.loaded_system = True

    def set_missing_host_key_policy(self, policy: object) -> None:
        self.policy = policy

    def close(self) -> None:
        return None


def test_paramiko_transport_rejects_unknown_hosts_by_default(monkeypatch) -> None:
    fake_client = _FakeParamikoClient()
    monkeypatch.setattr(paramiko, "SSHClient", lambda: fake_client)

    ParamikoSshTransport(
        SshConfig(host="example-host", private_key_path="~/.ssh/id_ed25519")
    )

    assert isinstance(fake_client.policy, paramiko.RejectPolicy)
    assert fake_client.loaded_system is True


def test_paramiko_transport_allows_unknown_hosts_when_enabled(monkeypatch) -> None:
    fake_client = _FakeParamikoClient()
    monkeypatch.setattr(paramiko, "SSHClient", lambda: fake_client)

    ParamikoSshTransport(
        SshConfig(
            host="example-host",
            private_key_path="~/.ssh/id_ed25519",
            allow_unknown_hosts=True,
            known_hosts_path="~/.ssh/known_hosts",
        )
    )

    assert isinstance(fake_client.policy, paramiko.AutoAddPolicy)
    assert fake_client.loaded_host_keys is not None
