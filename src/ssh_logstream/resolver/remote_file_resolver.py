"""
ssh_logstream.resolver.remote_file_resolver
==========================================

Remote file discovery and member-style resolution.

Overview
--------
This module resolves a caller-provided target name to exactly one remote file
path discovered inside a configured folder.

Resolution semantics
--------------------
- Candidate paths are gathered remotely by `find`.
- If the target contains no path separator, exact basename matches are
  preferred.
- If no basename match exists, suffix matching is used.
- Multiple matches raise `RemoteFileAmbiguityError`.
- No matches raise `RemoteFileNotFoundError`.

Design goals
------------
- Deterministic file selection
- Compatibility with ziplogstream-style member targeting ergonomics
- Clear separation between path discovery and SSH transport concerns
"""

from __future__ import annotations

import logging
import posixpath

log = logging.getLogger(__name__)

from ssh_logstream.commands import build_find_file_command
from ssh_logstream.errors import RemoteFileAmbiguityError, RemoteFileNotFoundError
from ssh_logstream.models import ResolvedFile
from ssh_logstream.transport import SshTransport


class RemoteFileResolver:
    """Resolve exactly one remote file path for a folder and filename."""

    def __init__(self, transport: SshTransport) -> None:
        self._transport = transport

    def resolve(self, *, folder: str, filename: str) -> ResolvedFile:
        """Return a single resolved file or raise a precise resolution error."""

        log.debug("resolving %r in %r", filename, folder)
        command = build_find_file_command(folder=folder, filename=filename)
        output = self._transport.execute_text(command)
        candidates = [path for path in output.split("\x00") if path]
        log.debug("find returned %d candidate(s)", len(candidates))
        matches = resolve_remote_member(candidates, filename)
        if not matches:
            log.warning("no match found for %r in %r", filename, folder)
            raise RemoteFileNotFoundError(
                f"No remote file named {filename!r} was found in {folder!r}."
            )
        if len(matches) > 1:
            log.warning(
                "ambiguous match for %r in %r: %d candidates",
                filename,
                folder,
                len(matches),
            )
            rendered = ", ".join(sorted(matches))
            raise RemoteFileAmbiguityError(
                f"Multiple remote files named {filename!r} were found in {folder!r}: {rendered}."
            )
        log.debug("resolved %r -> %r", filename, matches[0])
        return ResolvedFile(folder=folder, filename=filename, path=matches[0])


def resolve_remote_member(candidates: list[str], target: str) -> list[str]:
    """Resolve a target path using basename-preferred member semantics."""

    normalized_target = target.replace("\\", "/")
    if "/" not in normalized_target:
        basename_matches = [
            candidate
            for candidate in candidates
            if posixpath.basename(candidate) == normalized_target
        ]
        if basename_matches:
            return basename_matches
    suffix = f"/{normalized_target}"
    return [
        candidate
        for candidate in candidates
        if candidate == normalized_target or candidate.endswith(suffix)
    ]
