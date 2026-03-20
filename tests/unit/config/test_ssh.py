"""Unit tests for SSH configuration validation."""

from __future__ import annotations

import pytest

from ssh_logstream import ConfigurationError, SshConfig


def test_ssh_config_expands_paths() -> None:
    ssh_config = SshConfig(
        host="example-host",
        username="logsync",
        private_key_path="~/.ssh/id_ed25519",
        known_hosts_path="~/.ssh/known_hosts",
    )

    assert ssh_config.private_key_path is not None
    assert ".ssh" in ssh_config.private_key_path
    assert ssh_config.known_hosts_path is not None
    assert ".ssh" in ssh_config.known_hosts_path


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"host": ""}, "host"),
        ({"host": "example", "port": 0}, "port"),
        (
            {"host": "example", "private_key_path": "~/.ssh/id", "connect_timeout_seconds": 0.0},
            "connect_timeout_seconds",
        ),
        (
            {"host": "example", "private_key_path": "~/.ssh/id", "keepalive_seconds": -1},
            "keepalive_seconds",
        ),
        ({"host": "example"}, "At least one of private_key_path or password"),
    ],
)
def test_ssh_config_rejects_invalid_inputs(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        SshConfig(**kwargs)  # type: ignore[arg-type]


def test_ssh_config_supports_password_only_and_disabled_keepalive() -> None:
    ssh_config = SshConfig(
        host="example-host",
        password="secret",
        keepalive_seconds=0,
        allow_unknown_hosts=True,
    )

    assert ssh_config.password == "secret"
    assert ssh_config.keepalive_seconds == 0
    assert ssh_config.allow_unknown_hosts is True
