"""Unit tests for streaming configuration validation."""

from __future__ import annotations

import pytest

from ssh_logstream import ConfigurationError, LineStreamerConfig


def test_line_streamer_config_validates_limits_and_codecs() -> None:
    with pytest.raises(ConfigurationError, match="max_line_bytes"):
        LineStreamerConfig(chunk_size=1024, max_line_bytes=512)

    with pytest.raises(ConfigurationError, match="Unsupported encoding"):
        LineStreamerConfig(encoding="not-a-real-codec")

    with pytest.raises(ConfigurationError, match="Unsupported decode error handler"):
        LineStreamerConfig(errors="not-a-real-handler")


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32", "utf-8-sig"])
def test_line_streamer_config_rejects_bom_injecting_encodings(encoding: str) -> None:
    with pytest.raises(ConfigurationError, match="byte-order mark"):
        LineStreamerConfig(encoding=encoding)


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be", "utf-8"])
def test_line_streamer_config_accepts_explicit_byte_order_encodings(encoding: str) -> None:
    cfg = LineStreamerConfig(encoding=encoding)
    assert cfg.encoding == encoding


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"])
def test_line_streamer_config_rejects_ignore_errors_with_non_ascii_compatible_encoding(
    encoding: str,
) -> None:
    with pytest.raises(ConfigurationError, match="errors='ignore'"):
        LineStreamerConfig(encoding=encoding, errors="ignore")


def test_line_streamer_config_accepts_ignore_errors_with_ascii_compatible_encoding() -> None:
    cfg = LineStreamerConfig(encoding="utf-8", errors="ignore")
    assert cfg.errors == "ignore"

