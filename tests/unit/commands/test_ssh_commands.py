"""Unit tests for remote shell command construction."""

from __future__ import annotations

from ssh_logstream.commands import (
    build_find_file_command,
    build_follow_stream_command,
    build_snapshot_stream_command,
)


def test_build_find_file_command_simple_basename_uses_name_filter() -> None:
    command = build_find_file_command(folder="/var/log/my app", filename="app.log")

    assert command == "find '/var/log/my app' -type f -name app.log -print0"


def test_build_find_file_command_escapes_glob_metacharacters_in_basename() -> None:
    command = build_find_file_command(folder="/var/log", filename="tricky[1].log")

    assert command == r"find /var/log -type f -name 'tricky\[1].log' -print0"


def test_build_find_file_command_escapes_wildcard_metacharacters_in_basename() -> None:
    command = build_find_file_command(folder="/var/log", filename="app*.log")

    assert command == r"find /var/log -type f -name 'app\*.log' -print0"


def test_build_find_file_command_path_fragment_lists_all_files() -> None:
    command = build_find_file_command(folder="/var/log/myapp", filename="service-a/app.log")

    assert command == "find /var/log/myapp -type f -print0"


def test_build_stream_commands_support_snapshot_and_follow_modes() -> None:
    snapshot = build_snapshot_stream_command(path="/var/log/app.log")
    follow = build_follow_stream_command(path="/var/log/app.log")

    assert snapshot == "cat -- /var/log/app.log"
    assert follow == "tail -n +1 -F -- /var/log/app.log"
