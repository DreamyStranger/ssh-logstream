# Development

## Local setup

```bash
pip install -e .[dev]
```

## Checks

```bash
pytest
ruff check .
mypy src
```

## Manual performance tools

The repository also includes manual performance scripts under `scripts/`:

- `scripts/benchmark_streaming.py`: repeated benchmark runs across one or more
  real remote files, or local files in a no-SSH mode
- `scripts/stress_large_remote_file.py`: single-target stress test for very
  large remote files, or a local file in a no-SSH mode
- `scripts/benchmark_streaming.example.json`: example saved config for the
  benchmark script
- `scripts/stress_large_remote_file.example.json`: example saved config for the
  stress script

In local mode, both scripts can reuse generated fixtures so repeated runs do
not need to recreate benchmark data.

Both scripts also accept `--config PATH` so settings can be stored in JSON and
rerun without retyping long CLI commands.

These scripts are intentionally not part of the automated test suite.

## Testing strategy

- unit tests cover config validation, command building, resolver behavior, and
  incremental line decoding
- README usage is exercised through high-level `LineStreamer` tests
- integration tests are optional and enabled through SSH environment variables
- resolver tests cover basename-preferred member resolution semantics
- streaming tests should cover chunk boundaries, encodings, and oversized lines

## Contribution guidelines

- keep module responsibilities narrow
- preserve the README contract for the public API
- maintain bounded-memory behavior for streaming changes
- preserve SSH configuration semantics and host-verification defaults
- add or update tests with every behavior change
