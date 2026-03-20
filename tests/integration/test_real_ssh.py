"""Integration tests against a real SSH-accessible host.

These tests are optional and environment-driven. Each test skips when the
specific environment variables required for that scenario are not configured.
"""

from __future__ import annotations

import pytest

from ssh_logstream import (
    LineStreamer,
    RemoteFileAmbiguityError,
    RemoteFileNotFoundError,
)
from tests.integration._helpers import build_integration_ssh_config, parse_expected_lines


def _require_value(value: str, env_name: str) -> str:
    if not value:
        pytest.skip(f"{env_name} is not configured.")
    return value


@pytest.mark.integration
def test_snapshot_stream_matches_expected_lines(integration_env: dict[str, str]) -> None:
    filename = _require_value(integration_env["filename"], "SSH_LOGSTREAM_TEST_FILENAME")
    expected_lines = parse_expected_lines(integration_env)
    streamer = LineStreamer(
        folder=integration_env["folder"],
        filename=filename,
        ssh_config=build_integration_ssh_config(integration_env),
    )

    assert list(streamer.stream()) == expected_lines


@pytest.mark.integration
def test_missing_remote_file_raises_not_found(integration_env: dict[str, str]) -> None:
    filename = _require_value(
        integration_env["missing_filename"],
        "SSH_LOGSTREAM_TEST_MISSING_FILENAME",
    )
    streamer = LineStreamer(
        folder=integration_env["folder"],
        filename=filename,
        ssh_config=build_integration_ssh_config(integration_env),
    )

    with pytest.raises(RemoteFileNotFoundError):
        list(streamer.stream())


@pytest.mark.integration
def test_ambiguous_remote_file_raises_ambiguity(integration_env: dict[str, str]) -> None:
    filename = _require_value(
        integration_env["ambiguous_filename"],
        "SSH_LOGSTREAM_TEST_AMBIGUOUS_FILENAME",
    )
    streamer = LineStreamer(
        folder=integration_env["folder"],
        filename=filename,
        ssh_config=build_integration_ssh_config(integration_env),
    )

    with pytest.raises(RemoteFileAmbiguityError):
        list(streamer.stream())


@pytest.mark.integration
def test_suffix_member_resolution_selects_specific_file(integration_env: dict[str, str]) -> None:
    filename = _require_value(
        integration_env["suffix_filename"],
        "SSH_LOGSTREAM_TEST_SUFFIX_FILENAME",
    )
    streamer = LineStreamer(
        folder=integration_env["folder"],
        filename=filename,
        ssh_config=build_integration_ssh_config(integration_env),
    )

    first_line = next(iter(streamer.stream()))

    assert isinstance(first_line, str)
