"""
ssh_logstream.commands.ssh_commands
==================================

Remote shell command construction helpers.

Overview
--------
This module builds the small set of remote shell commands required by the
library for file discovery and byte streaming.

Contract
--------
- Commands are construction-only; they do not execute anything.
- All dynamic path inputs are shell-quoted.
- Resolution commands return candidate file paths for downstream matching.
"""

from __future__ import annotations

from shlex import quote


def _shell_quote(value: str) -> str:
    return quote(value)


def _escape_find_name(name: str) -> str:
    """Escape find(1) -name glob metacharacters so the pattern matches literally.

    POSIX find treats ``*``, ``?``, ``[``, and ``\\`` as glob metacharacters
    inside the ``-name`` expression.  Backslash-escaping them causes find to
    match the literal characters instead.
    """
    return name.replace("\\", "\\\\").replace("*", "\\*").replace("?", "\\?").replace("[", "\\[")


def build_find_file_command(*, folder: str, filename: str) -> str:
    """Build a command that lists candidate files for resolution.

    When `filename` is a simple basename (no path separator), the search is
    restricted with ``-name`` so only matching files are transmitted over SSH.
    Glob metacharacters (``*``, ``?``, ``[``, ``\\``) are escaped so the match
    is always literal.  For path-fragment targets (containing ``/``), all files
    under `folder` are listed and the Python resolver filters them locally.
    """

    quoted_folder = _shell_quote(folder)
    normalized = filename.replace("\\", "/")
    if "/" not in normalized:
        return f"find {quoted_folder} -type f -name {_shell_quote(_escape_find_name(normalized))} -print0"
    return f"find {quoted_folder} -type f -print0"


def build_snapshot_stream_command(*, path: str) -> str:
    """Build the remote command used for one-shot streaming."""

    return f"cat -- {_shell_quote(path)}"


def build_follow_stream_command(*, path: str) -> str:
    """Build the remote command used for follow-mode streaming."""

    return f"tail -n +1 -F -- {_shell_quote(path)}"
