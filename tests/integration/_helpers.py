"""Helper functions for real-SSH integration tests."""

from __future__ import annotations

import json

import pytest

from ssh_logstream import SshConfig


def build_integration_ssh_config(env: dict[str, str]) -> SshConfig:
    """Build an `SshConfig` object from integration environment values."""

    private_key_path = env["private_key_path"] or None
    password = env["password"] or None
    username = env["username"] or None
    known_hosts_path = env["known_hosts_path"] or None
    allow_unknown_hosts = env["allow_unknown_hosts"] in {"1", "true", "yes"}
    return SshConfig(
        host=env["host"],
        username=username,
        private_key_path=private_key_path,
        password=password,
        known_hosts_path=known_hosts_path,
        allow_unknown_hosts=allow_unknown_hosts,
    )


def parse_expected_lines(env: dict[str, str]) -> list[str]:
    """Parse expected integration lines from JSON or skip when absent."""

    payload = env["expected_lines_json"]
    if not payload:
        pytest.skip("SSH_LOGSTREAM_TEST_EXPECTED_LINES_JSON is not configured.")
    data = json.loads(payload)
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        raise AssertionError(
            "SSH_LOGSTREAM_TEST_EXPECTED_LINES_JSON must be a JSON array of strings."
        )
    return data
