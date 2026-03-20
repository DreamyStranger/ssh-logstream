# Architecture

`ssh-logstream` is split into narrow modules so the public API stays small while
SSH, resolution, and decoding concerns remain independently testable.

## Flow

1. `LineStreamer` validates high-level inputs and creates the SSH transport.
2. `RemoteFileResolver` executes a deterministic remote `find` command.
3. Exactly one `ResolvedFile` is required before streaming can begin.
4. The transport opens a raw byte stream for either snapshot or follow mode.
5. `LineStreamerCore` combines `IncrementalDecoder` and `LineBuffer` to emit lines.

`RemoteFileResolver` uses a basename-preferred member resolution step so callers
can target either `app.log` or a suffix such as `service-a/app.log`.

When `filename` contains no path separator, the remote `find` command is issued
with `-name <filename>` to avoid transmitting the full directory listing over
SSH.  `find`'s `-name` flag interprets `*`, `?`, and `[...]` as glob patterns
rather than literal characters.  Filenames that contain these characters should
be passed as path-fragment targets (e.g. `"subdir/tricky[1].log"`) so the
full-listing fallback path is used and Python-side exact matching applies.

The transport is also responsible for:

- strict host verification by default
- optional trust-on-first-use when explicitly enabled
- keepalive configuration for long-lived follow sessions

## Module boundaries

- `client/`: high-level orchestration and public entry point
- `config/`: validated dataclass configuration objects
- `resolver/`: exact-one remote file discovery
- `transport/`: SSH connection handling and raw byte streaming
- `streaming/`: incremental decode and newline splitting
- `commands/`: shell-safe command construction only
- `models/`: immutable structured result types
- `errors/`: precise exception hierarchy

## Bounded memory

The implementation retains only three categories of state while streaming:

- the current SSH read chunk
- incremental decoder state
- the current partial line buffer

File size does not influence memory growth.
