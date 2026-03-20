# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added

- `CHANGELOG.md` (this file).
- `StreamStats` dataclass (`bytes_read`, `chunks_read`, `lines_emitted`) exposed
  via `LineStreamer.stats`.  The object is created fresh on each `stream()` call
  and updated live during iteration, so callers can read throughput counters after
  the loop or sample them mid-stream in follow mode.
- `types-paramiko` added to `[project.optional-dependencies] dev` so `mypy --strict` passes out of the box after `pip install -e .[dev]`.

### Changed

- **`ConnectionError` renamed to `SshConnectionError`** to avoid shadowing the
  Python built-in of the same name.  Update any `except ConnectionError` or
  `from ssh_logstream import ConnectionError` calls accordingly.
- `build_find_file_command` now issues `find -name <filename>` for simple
  basename targets (no path separator), avoiding a full directory listing over
  SSH.  Path-fragment targets (containing `/`) continue to use the full listing
  with Python-side filtering.  See the architecture docs for the `find` glob
  caveat.
- `_is_ascii_compatible_encoding` result is now cached per encoding name
  (`@functools.cache`), eliminating the 128-encode probe on every `stream()` call.
- `LineBuffer` compaction now fires once per chunk batch (at the end of
  `pop_lines` / `pop_text_lines`) rather than after every individual line,
  removing ~850 k redundant method calls per second in the ASCII fast path.
- `LineBuffer` compaction threshold changed from a hard-coded 65 536-byte
  absolute limit to a pure ratio-based condition (`_raw_start ≥ len(buffer) // 2`),
  reducing total memmove by up to 7× for large `chunk_size` values.
- Per-line `bytes` slice replaced with an inline `memoryview` in the ASCII fast
  path, halving per-line allocations from two copies to zero.
- `_read_command_output` now sleeps 5 ms between poll iterations instead of
  busy-waiting, preventing 100 % CPU spin while a remote command is running.

### Fixed

- `build_find_file_command` now escapes `find -name` glob metacharacters (`*`,
  `?`, `[`, `\`) in simple-basename targets so that filenames such as
  `tricky[1].log` are matched literally rather than treated as glob patterns.
  Previously a filename containing `[` or `*` could silently match unintended
  files or return zero results.
- `LineStreamerConfig` now rejects BOM-injecting encodings (`utf-16`, `utf-32`,
  `utf-8-sig`) at construction time with a `ConfigurationError` that directs
  callers to the explicit byte-order variants (`utf-16-le`, `utf-16-be`, etc.).
  These encodings prepend a BOM on every `encode()` call, which broke the
  suffix-encoding arithmetic used by `_find_raw_prefix_length`.
- `LineStreamerConfig` now rejects `errors='ignore'` when paired with a
  non-ASCII-compatible encoding (`utf-16-le`, `utf-16-be`, `utf-32-le`,
  `utf-32-be`).  Silently dropped bytes cause the suffix-encoding arithmetic
  in `_find_raw_prefix_length` to miscalculate raw byte boundaries.  Use
  `errors='replace'` or `errors='strict'` instead.
- `_find_raw_prefix_length` (generic / non-ASCII-compatible path) previously
  created a fresh incremental decoder, which misidentified bytes at the start of
  a raw chunk that completed a multi-byte character begun in the previous chunk
  (e.g. UTF-16-LE across a 5-byte chunk boundary).  The function now uses
  suffix-encoding arithmetic instead, which is correct regardless of cross-chunk
  carry-over state.
- `_consume_decoded_prefix` no longer calls `_decode_line(raw_chunk[:prefix_bytes])`
  on the sub-chunk that starts mid-character; it uses decoded character-count
  arithmetic directly.
- Added missing `import pytest` in `tests/unit/client/test_line_streamer.py`
  that caused one test to raise `NameError` at runtime.

---

## [0.1.0] — initial release

- Initial public release.
