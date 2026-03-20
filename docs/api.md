# API

## Public imports

```python
from ssh_logstream import (
    LineStreamer,
    LineStreamerConfig,
    SshConfig,
    StreamStats,
    SshLogStreamError,
    ConfigurationError,
    SshConnectionError,
    RemoteFileNotFoundError,
    RemoteFileAmbiguityError,
)
```

## `SshConfig`

Create validated SSH settings:

```python
ssh_config = SshConfig(
    host="example-host",
    username="logsync",
    private_key_path="~/.ssh/id_ed25519",
    connect_timeout_seconds=30.0,
    keepalive_seconds=10,
)
```

## `LineStreamerConfig`

Override streaming defaults when needed:

```python
config = LineStreamerConfig(
    chunk_size=1 << 20,
    encoding="utf-8",
    errors="replace",
    max_line_bytes=32 * (1 << 20),
)
```

## `LineStreamer`

Primary entry point:

```python
streamer = LineStreamer(
    folder="/var/log/myapp",
    filename="app.log",
    ssh_config=ssh_config,
    config=config,
)
```

Stream lines:

```python
for line in streamer.stream():
    print(line)
```

Follow mode is available through `stream(follow=True)`.

## `StreamStats`

Accumulated counters for a single `stream()` call, available via `streamer.stats`:

```python
streamer = LineStreamer(...)
for line in streamer.stream():
    process(line)

stats = streamer.stats
print(f"{stats.lines_emitted} lines, {stats.bytes_read / 1e6:.1f} MB, {stats.chunks_read} chunks")
```

Fields:

- `bytes_read`: raw bytes received from the SSH channel
- `chunks_read`: number of SSH read calls (high value relative to `bytes_read` indicates `chunk_size` is too small)
- `lines_emitted`: complete lines yielded, including the final partial line at EOF

Stats are reset when a new `stream()` iterator begins producing values and
update live during iteration.
In follow mode they accumulate until the caller breaks out of the loop.

## Member resolution

Remote file resolution uses basename-preferred member semantics.

- If `filename` contains no path separator, exact basename matches are preferred
- If no basename match exists, suffix matching is used
- Multiple matches raise `RemoteFileAmbiguityError`
- No matches raise `RemoteFileNotFoundError`

Example:

```python
streamer = LineStreamer(
    folder="/var/log/myapp",
    filename="service-a/app.log",
    ssh_config=ssh_config,
)
```
