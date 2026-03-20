# ssh-logstream

![CI](https://github.com/DreamyStranger/ssh-logstream/actions/workflows/ci.yml/badge.svg)
[![Python Versions](https://img.shields.io/pypi/pyversions/ssh-logstream.svg)](https://pypi.org/project/ssh-logstream/)
![License](https://img.shields.io/github/license/DreamyStranger/ssh-logstream.svg)
![Tests](https://img.shields.io/badge/tests-pytest-blue)

**Streaming line reader for large remote log files over SSH.**

`ssh-logstream` provides a fast, memory-bounded way to iterate over text lines
from a file located on a remote machine via SSH without copying the file
locally and without loading the entire file into memory.

It is designed for large log processing pipelines where remote files may be
hundreds of megabytes or gigabytes in size.

---

## Features

* **True streaming over SSH**

  * Reads remote files incrementally
  * No local file copy required
  * No full file buffering

* **Bounded memory usage**

  * Memory stays flat regardless of file size
  * Controlled buffering for partial lines
  * Safe handling of oversized lines

* **Deterministic file resolution**

  * Searches within a specified remote folder
  * Enforces exactly one match
  * Detects ambiguity and missing files

* **Incremental decoding**

  * Handles chunk boundaries safely
  * Configurable encoding and error policy

* **Snapshot and follow modes**

  * Read full file once
  * Or continuously stream appended log data

* **Fully typed**

  * Includes `py.typed` for static type checking

---

## Installation

Install from PyPI:

```bash
pip install ssh-logstream
```

Or install from source:

```bash
pip install .
```

Or in development mode:

```bash
pip install -e .[dev]
```

Python **3.10+** is required.

---

## Quick Start

```python
from ssh_logstream import LineStreamer, SshConfig

ssh_config = SshConfig(
    host="example-host",
    username="logsync",
    private_key_path="~/.ssh/id_ed25519",
)

streamer = LineStreamer(
    folder="/var/log/myapp",
    filename="app.log",
    ssh_config=ssh_config,
)

for line in streamer.stream():
    print(line)
```

This will:

* connect to the remote host via SSH
* locate `app.log` inside `/var/log/myapp`
* stream decoded lines one by one

No file download or full buffering occurs.

---

## Configuration

Streaming behavior can be configured using `LineStreamerConfig`.

```python
from ssh_logstream import LineStreamer, LineStreamerConfig, SshConfig

ssh_config = SshConfig(
    host="example-host",
    username="logsync",
    private_key_path="~/.ssh/id_ed25519",
)

config = LineStreamerConfig(
    chunk_size=1 << 20,                # 1 MiB SSH read chunks
    encoding="utf-8",
    errors="replace",
    max_line_bytes=32 * (1 << 20),     # 32 MiB max line buffer
)

streamer = LineStreamer(
    folder="/var/log/myapp",
    filename="app.log",
    ssh_config=ssh_config,
    config=config,
)

for line in streamer.stream():
    print(line)
```

### Configuration options

| Option           | Description                                    |
| ---------------- | ---------------------------------------------- |
| `chunk_size`     | Number of bytes read per chunk from SSH stream |
| `encoding`       | Text encoding used when decoding bytes         |
| `errors`         | Error handler for decoding                     |
| `max_line_bytes` | Max buffered bytes for a partial line          |

### Notes

* `chunk_size` must be positive
* `max_line_bytes` must be >= `chunk_size`
* oversized lines are safely handled to prevent memory growth
* BOM-injecting encodings (`utf-16`, `utf-32`, `utf-8-sig`) are rejected; use `utf-16-le`, `utf-16-be`, `utf-32-le`, or `utf-32-be` instead

---

## Remote File Resolution

The library must resolve **exactly one file**.

The default resolver behaves as follows:

1. Search recursively inside the given folder
2. If `filename` contains no path separator, prefer exact basename matches
3. If no basename match exists, fall back to suffix matching
4. If multiple matches exist, `RemoteFileAmbiguityError` is raised
5. If no match exists, `RemoteFileNotFoundError` is raised

This ensures deterministic behavior.

Example remote folder:

```text
/var/log/myapp/
|-- service-a/app.log
`-- service-b/app.log
```

Calling:

```python
from ssh_logstream import LineStreamer, SshConfig

ssh_config = SshConfig(
    host="example-host",
    username="logsync",
    private_key_path="~/.ssh/id_ed25519",
)

LineStreamer(
    folder="/var/log/myapp",
    filename="app.log",
    ssh_config=ssh_config,
)
```

would raise an ambiguity error because two files match.

You can instead target a specific suffix:

```python
from ssh_logstream import LineStreamer, SshConfig

ssh_config = SshConfig(
    host="example-host",
    username="logsync",
    private_key_path="~/.ssh/id_ed25519",
)

LineStreamer(
    folder="/var/log/myapp",
    filename="service-a/app.log",
    ssh_config=ssh_config,
)
```

---

## SSH Configuration

```python
from ssh_logstream import SshConfig

ssh_config = SshConfig(
    host="example-host",
    port=22,
    username="logsync",
    private_key_path="~/.ssh/id_ed25519",
    connect_timeout_seconds=30.0,
    keepalive_seconds=10,
    known_hosts_path="~/.ssh/known_hosts",
    allow_unknown_hosts=False,
)
```

### Authentication

* Use **private key** (recommended)
* Or password (less secure)
* At least one of `private_key_path` or `password` is required

### Host verification

* Unknown hosts are rejected by default
* Set `allow_unknown_hosts=True` only in controlled environments

---

## Streaming Modes

### Snapshot Mode (default)

* Reads file from beginning to end
* Terminates at EOF

### Follow Mode

* Continuously streams appended lines
* Suitable for live logs
* The iterator does **not** terminate at EOF; the caller is responsible for breaking out of the loop

---

## Public API

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

### Session stats

After (or during) a `stream()` call, `streamer.stats` exposes a `StreamStats` object:

```python
from ssh_logstream import LineStreamer, SshConfig

ssh_config = SshConfig(
    host="example-host",
    username="logsync",
    private_key_path="~/.ssh/id_ed25519",
)

streamer = LineStreamer(
    folder="/var/log/myapp",
    filename="app.log",
    ssh_config=ssh_config,
)

for line in streamer.stream():
    print(line)

stats = streamer.stats
print(f"{stats.lines_emitted} lines / {stats.bytes_read / 1e6:.1f} MB / {stats.chunks_read} chunks")
```

| Field | Description |
| --- | --- |
| `bytes_read` | Raw bytes received from the SSH channel |
| `chunks_read` | SSH read calls issued |
| `lines_emitted` | Complete lines yielded, including the final partial line |

Stats reset when a new `stream()` iterator begins producing values.

---

## Error Handling

```python
from ssh_logstream import (
    ConfigurationError,
    LineStreamer,
    RemoteFileAmbiguityError,
    RemoteFileNotFoundError,
    SshConfig,
)

try:
    ssh_config = SshConfig(
        host="example-host",
        username="logsync",
        private_key_path="~/.ssh/id_ed25519",
    )
    streamer = LineStreamer(
        folder="/var/log/myapp",
        filename="app.log",
        ssh_config=ssh_config,
    )
    for line in streamer.stream():
        print(line)
except RemoteFileNotFoundError:
    print("remote file not found")
except RemoteFileAmbiguityError:
    print("remote file resolution was ambiguous")
except ConfigurationError:
    print("configuration was invalid")
```

---

## Line Semantics

* newline characters removed
* CRLF normalized
* final partial line emitted
* empty lines preserved
* oversized lines handled safely

---

## Bounded Memory Behavior

Memory usage depends only on:

* `chunk_size`
* current partial line
* decoding state

It does **not** depend on file size.

This allows streaming arbitrarily large remote files safely.

---

## Project Structure

```text
ssh-logstream/
|-- .github/
|   `-- workflows/
|       |-- ci.yml
|       `-- release.yml
|-- src/
|   `-- ssh_logstream/
|       |-- __init__.py
|       |-- py.typed
|       |-- client/
|       |   `-- line_streamer.py
|       |-- config/
|       |   |-- ssh.py
|       |   `-- streamer.py
|       |-- resolver/
|       |   `-- remote_file_resolver.py
|       |-- transport/
|       |   `-- ssh_transport.py
|       |-- streaming/
|       |   |-- decoder.py
|       |   |-- line_buffer.py
|       |   `-- line_streamer_core.py
|       |-- commands/
|       |   `-- ssh_commands.py
|       |-- models/
|       |   |-- line_record.py
|       |   |-- resolved_file.py
|       |   `-- stream_stats.py
|       `-- errors/
|           `-- exceptions.py
|-- tests/
|   |-- unit/
|   `-- integration/
|-- scripts/
|   |-- benchmark_streaming.py
|   |-- benchmark_streaming.example.json
|   |-- stress_large_remote_file.example.json
|   `-- stress_large_remote_file.py
|-- docs/
|   |-- architecture.md
|   |-- streaming-model.md
|   |-- configuration.md
|   |-- api.md
|   |-- error-model.md
|   `-- development.md
|-- README.md
|-- LICENSE
`-- pyproject.toml
```

### Structure Overview

* `client/` -- public API (`LineStreamer`)
* `config/` -- configuration objects and validation
* `resolver/` -- remote file discovery
* `transport/` -- SSH execution and byte streaming
* `streaming/` -- decoding and line assembly
* `commands/` -- remote shell command construction
* `models/` -- structured data objects
* `errors/` -- exception hierarchy

This separation ensures:

* clear responsibility boundaries
* maintainable architecture
* easier testing and extension
* compatibility with AI-assisted development

---

## Development

```bash
pip install -e .[dev]
pytest
```

Manual performance tools are also available under `scripts/` for on-demand
benchmarking and large-file stress testing, with both real SSH and local
no-SSH modes. Both scripts also accept `--config PATH` so you can keep saved
benchmark settings in JSON files, and in local mode generated benchmark files
are reused if they already exist.

---

## License

MIT License
