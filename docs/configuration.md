# Configuration

## `SshConfig`

`SshConfig` controls SSH connectivity and authentication.

Fields:

- `host`: required non-empty hostname or address
- `port`: TCP port, default `22`
- `username`: optional SSH username
- `private_key_path`: optional private key path, `~` expanded
- `password`: password authentication or private-key passphrase
- `connect_timeout_seconds`: positive TCP, banner, and auth timeout in seconds; does not apply to remote command execution after the connection is established
- `keepalive_seconds`: keepalive interval in seconds, default `10`, `0` disables
- `known_hosts_path`: optional known-hosts file path, `~` expanded
- `allow_unknown_hosts`: when `True`, accept unknown host keys automatically

Validation and behavior:

- at least one of `private_key_path` or `password` is required
- unknown hosts are rejected by default
- `allow_unknown_hosts=True` should only be used in controlled environments
- default SSH agent and implicit key discovery are intentionally disabled
- `keepalive_seconds=10` is the default for long-lived streaming sessions
- `connect_timeout_seconds` covers TCP connection, SSH banner exchange, and authentication only; once a remote command is running it can block indefinitely — callers that need a hard deadline should wrap `stream()` with their own timeout mechanism (e.g. `signal.alarm` or a thread with a `threading.Event`)

## `LineStreamerConfig`

`LineStreamerConfig` controls chunking and decoding.

Fields:

- `chunk_size`: positive SSH read size in bytes
- `encoding`: Python codec name used for incremental decoding
- `errors`: Python decode error handler such as `strict` or `replace`
- `max_line_bytes`: positive line-buffer ceiling in bytes

Validation rules:

- `chunk_size` must be positive
- `max_line_bytes` must be positive
- `max_line_bytes` must be greater than or equal to `chunk_size`
- `encoding` and `errors` must be recognized by Python codecs
- BOM-injecting encodings (`utf-16`, `utf-32`, `utf-8-sig`) are rejected; use the
  explicit byte-order variants instead (`utf-16-le`, `utf-16-be`, `utf-32-le`,
  `utf-32-be`)
- `errors='ignore'` is rejected when paired with a non-ASCII-compatible encoding;
  silently dropped bytes break raw-byte boundary arithmetic — use `errors='replace'`
  or `errors='strict'` instead

`max_line_bytes` is measured in raw buffered bytes for the current partial line.
