# Streaming Model

`ssh-logstream` is designed for large remote files where copying to local disk
or reading the entire file into memory is not acceptable.

## Data path

The remote command writes bytes to stdout, the SSH transport yields bounded
chunks, and the streaming layer emits complete logical lines as soon as newline
boundaries can be resolved.

- For ASCII-compatible encodings such as UTF-8, the line buffer uses a fast
  raw-byte newline scanner and decodes complete lines only when they are ready
  to emit.
- For non-ASCII-compatible encodings such as UTF-16-LE and UTF-16-BE, the
  incremental decoder produces text fragments and the line buffer maps decoded
  newline boundaries back to the originating raw bytes.

## Line handling rules

- newline characters are removed from emitted values
- `\r\n` is normalized to a single logical line ending
- empty lines are preserved
- a final partial line is emitted even when the file does not end with `\n`

## Oversized lines

`max_line_bytes` caps the buffered bytes for a single in-progress line. If the
limit would be exceeded before a newline arrives, `LineTooLongError` is raised.

The limit is enforced against raw buffered bytes, not decoded character count.
This preserves the bounded-memory guarantee regardless of the configured text
encoding.

## Modes

- Snapshot mode: reads the file once from start to EOF
- Follow mode: replays the file and continues yielding appended lines indefinitely;
  the iterator does not terminate at EOF and must be broken out of by the caller

## Encoding model

The streaming pipeline supports any Python codec accepted by `codecs.lookup()`,
subject to two safety restrictions:

- BOM-injecting codec aliases (`utf-16`, `utf-32`, `utf-8-sig`) are rejected at
  configuration time; use the explicit byte-order variants (`utf-16-le`,
  `utf-16-be`, `utf-32-le`, `utf-32-be`) instead.
- `errors='ignore'` is rejected for non-ASCII-compatible encodings because
  silently dropped bytes break raw-byte boundary accounting.

UTF-8 and other ASCII-compatible encodings are the optimized path. Multi-byte
encodings such as UTF-16-LE and UTF-16-BE are still supported, but they use the
slower generic fallback path so the library can preserve correct line splitting
and bounded-memory accounting.
