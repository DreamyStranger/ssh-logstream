"""Shared pytest fixtures for the ssh-logstream test suite.

Overview
--------
This module keeps small, genuinely reusable fixtures in one place so unit and
integration tests can share common setup without duplicating boilerplate.

Guidelines
----------
- Keep fixtures here only when they are used across multiple test modules.
- Keep transport- and resolver-specific fakes local to the tests that own them.
- Prefer explicit fixtures over large implicit test state.
"""

from __future__ import annotations

import os

import pytest

from ssh_logstream import SshConfig


@pytest.fixture
def ssh_config() -> SshConfig:
    """Return a representative SSH configuration for unit tests."""

    return SshConfig(
        host="example-host",
        username="logsync",
        private_key_path="~/.ssh/id_ed25519",
    )


@pytest.fixture
def integration_env() -> dict[str, str]:
    """Return integration environment values or skip when they are not configured."""

    required = {
        "host": os.getenv("SSH_LOGSTREAM_TEST_HOST"),
        "folder": os.getenv("SSH_LOGSTREAM_TEST_FOLDER"),
    }
    if not all(required.values()):
        pytest.skip("Real SSH integration environment variables are not configured.")

    return {
        "host": required["host"] or "",
        "folder": required["folder"] or "",
        "username": os.getenv("SSH_LOGSTREAM_TEST_USERNAME", ""),
        "private_key_path": os.getenv("SSH_LOGSTREAM_TEST_PRIVATE_KEY", ""),
        "password": os.getenv("SSH_LOGSTREAM_TEST_PASSWORD", ""),
        "known_hosts_path": os.getenv("SSH_LOGSTREAM_TEST_KNOWN_HOSTS", ""),
        "allow_unknown_hosts": os.getenv("SSH_LOGSTREAM_TEST_ALLOW_UNKNOWN_HOSTS", "").lower(),
        "filename": os.getenv("SSH_LOGSTREAM_TEST_FILENAME", ""),
        "expected_lines_json": os.getenv("SSH_LOGSTREAM_TEST_EXPECTED_LINES_JSON", ""),
        "missing_filename": os.getenv("SSH_LOGSTREAM_TEST_MISSING_FILENAME", ""),
        "ambiguous_filename": os.getenv("SSH_LOGSTREAM_TEST_AMBIGUOUS_FILENAME", ""),
        "suffix_filename": os.getenv("SSH_LOGSTREAM_TEST_SUFFIX_FILENAME", ""),
    }
