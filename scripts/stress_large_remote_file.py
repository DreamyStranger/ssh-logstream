#!/usr/bin/env python3
"""
scripts.stress_large_remote_file
================================

Manual stress test for streaming a very large target with ``ssh-logstream``.

Overview
--------
Streams one remote or local text file through the production decoding and
line-emission path, measuring throughput, line count, decoded bytes, elapsed
time, and optional peak Python memory.

The script supports an optional JSON configuration file so stress settings can
be edited once and reused across later runs. CLI arguments always override
config file values.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ssh_logstream import LineStreamer, LineStreamerConfig, SshConfig  # noqa: E402
from ssh_logstream.streaming import LineStreamerCore  # noqa: E402

MiB = 1024 * 1024
GiB = 1024 * MiB
DEFAULT_MODE = "ssh"
DEFAULT_PORT = 22
DEFAULT_CONNECT_TIMEOUT_SECONDS = 30.0
DEFAULT_KEEPALIVE_SECONDS = 10
DEFAULT_LOCAL_PATH = Path(".benchmarks/large_logs_1g.log")
DEFAULT_SIZE_GIB = 1.0
DEFAULT_LINE_TEMPLATE = "INFO request completed status=200 latency_ms=12 path=/healthcheck\n"
DEFAULT_CHUNK_SIZE = 1 << 20
DEFAULT_MAX_LINE_BYTES = 32 * (1 << 20)
DEFAULT_ENCODING = "utf-8"
DEFAULT_ERRORS = "replace"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StressResult:
    """Metrics collected from one stress run."""

    host: str
    folder: str
    filename: str
    decoded_bytes: int
    line_count: int
    elapsed_seconds: float
    throughput_mib_per_sec: float
    peak_memory_bytes: int | None


# ---------------------------------------------------------------------------
# Configuration file support
# ---------------------------------------------------------------------------


def load_config_file(path: Path) -> dict[str, Any]:
    """Load one JSON stress config file."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in config file {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise SystemExit(f"Config file {path} must contain a JSON object")
    return cast(dict[str, Any], payload)


def resolve_value(
    cli_value: Any,
    config_data: dict[str, Any],
    key: str,
    default: Any,
) -> Any:
    """Resolve one config setting with CLI precedence."""

    if cli_value is not None:
        return cli_value
    if key in config_data:
        return config_data[key]
    return default


def resolve_bool(
    cli_flag: bool,
    config_data: dict[str, Any],
    key: str,
    default: bool,
) -> bool:
    """Resolve one boolean config setting with CLI precedence."""

    if cli_flag:
        return True
    raw_value = config_data.get(key)
    if raw_value is None:
        return default
    if not isinstance(raw_value, bool):
        raise SystemExit(f"Config key {key!r} must be true or false")
    return raw_value


def resolve_path(
    cli_value: Path | None,
    config_data: dict[str, Any],
    key: str,
    default: Path | None,
) -> Path | None:
    """Resolve one path config setting with CLI precedence."""

    if cli_value is not None:
        return cli_value
    raw_value = config_data.get(key)
    if raw_value is None:
        return default
    if not isinstance(raw_value, str):
        raise SystemExit(f"Config key {key!r} must be a string path")
    return Path(raw_value)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_bytes(num_bytes: int) -> str:
    """Format a byte count as a human-readable string."""

    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < MiB:
        return f"{num_bytes / 1024:.2f} KiB"
    if num_bytes < GiB:
        return f"{num_bytes / MiB:.2f} MiB"
    return f"{num_bytes / GiB:.2f} GiB"


def render_stress_report(result: StressResult) -> str:
    """Render a ``StressResult`` as a formatted multi-line report string."""

    lines = [
        "",
        "Streaming complete",
        "------------------",
        f"Host:             {result.host}",
        f"Folder:           {result.folder}",
        f"Filename:         {result.filename}",
        f"Decoded bytes:    {format_bytes(result.decoded_bytes)}",
        f"Lines streamed:   {result.line_count:,}",
        f"Elapsed time:     {result.elapsed_seconds:.2f} s",
        f"Throughput:       {result.throughput_mib_per_sec:.2f} MiB/s",
    ]
    if result.peak_memory_bytes is not None:
        lines.append(f"Peak Python mem:  {format_bytes(result.peak_memory_bytes)}")
    return "\n".join(lines)


def render_report_file(
    result: StressResult,
    ssh_config: SshConfig | None,
    config: LineStreamerConfig,
    mode: str,
    timestamp: str,
) -> str:
    """Render a file-ready stress report with a timestamped header."""

    header_lines = [
        "ssh-logstream Stress Test Results",
        "=" * 33,
        f"Run at:                  {timestamp}",
        f"mode:                    {mode}",
        f"chunk_size:              {config.chunk_size:,} bytes",
        f"max_line_bytes:          {config.max_line_bytes:,} bytes",
        f"encoding:                {config.encoding}",
        f"errors:                  {config.errors}",
    ]
    if ssh_config is not None:
        header_lines.extend(
            [
                f"host:                    {ssh_config.host}",
                f"port:                    {ssh_config.port}",
                f"username:                {ssh_config.username}",
                f"connect_timeout_seconds: {ssh_config.connect_timeout_seconds}",
                f"keepalive_seconds:       {ssh_config.keepalive_seconds}",
            ]
        )
    header = "\n".join(header_lines)
    return header + render_stress_report(result) + "\n"


# ---------------------------------------------------------------------------
# Local file generation
# ---------------------------------------------------------------------------


def generate_large_local_file(
    path: Path,
    target_size_bytes: int,
    *,
    line_template: str,
    encoding: str = "utf-8",
) -> None:
    """Generate a large local text file incrementally."""

    path.parent.mkdir(parents=True, exist_ok=True)

    encoded_line = line_template.encode(encoding)
    if not encoded_line:
        raise ValueError("line_template must not encode to empty bytes")

    line_size = len(encoded_line)
    written = 0

    with path.open("wb") as handle:
        while written < target_size_bytes:
            remaining = target_size_bytes - written
            chunk = encoded_line if remaining >= line_size else encoded_line[:remaining]
            handle.write(chunk)
            written += len(chunk)


# ---------------------------------------------------------------------------
# Streaming execution
# ---------------------------------------------------------------------------


def stream_large_remote_file(
    *,
    folder: str,
    filename: str,
    ssh_config: SshConfig,
    config: LineStreamerConfig,
    track_memory: bool,
) -> StressResult:
    """Stream one remote file and collect timing and throughput metrics."""

    if track_memory:
        tracemalloc.start()

    started = time.perf_counter()
    total_lines = 0
    total_decoded_bytes = 0

    streamer = LineStreamer(
        folder=folder,
        filename=filename,
        ssh_config=ssh_config,
        config=config,
    )
    for line in streamer.stream():
        total_lines += 1
        total_decoded_bytes += len(line.encode(config.encoding, errors=config.errors))

    elapsed = time.perf_counter() - started

    peak_memory_bytes: int | None = None
    if track_memory:
        _, peak_memory_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    throughput = (total_decoded_bytes / MiB) / elapsed if elapsed > 0 else 0.0

    return StressResult(
        host=ssh_config.host,
        folder=folder,
        filename=filename,
        decoded_bytes=total_decoded_bytes,
        line_count=total_lines,
        elapsed_seconds=elapsed,
        throughput_mib_per_sec=throughput,
        peak_memory_bytes=peak_memory_bytes,
    )


def stream_large_local_file(
    *,
    local_path: Path,
    config: LineStreamerConfig,
    track_memory: bool,
) -> StressResult:
    """Stream one local file through the decoding and line-emission pipeline."""

    if track_memory:
        tracemalloc.start()

    started = time.perf_counter()
    total_lines = 0
    total_decoded_bytes = 0
    core = LineStreamerCore(config)

    with local_path.open("rb") as handle:
        def chunks() -> Iterator[bytes]:
            while True:
                chunk = handle.read(config.chunk_size)
                if not chunk:
                    return
                yield chunk

        for record in core.iter_lines(chunks()):
            total_lines += 1
            total_decoded_bytes += len(record.text.encode(config.encoding, errors=config.errors))

    elapsed = time.perf_counter() - started

    peak_memory_bytes: int | None = None
    if track_memory:
        _, peak_memory_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    throughput = (total_decoded_bytes / MiB) / elapsed if elapsed > 0 else 0.0

    return StressResult(
        host="local",
        folder=str(local_path.parent),
        filename=local_path.name,
        decoded_bytes=total_decoded_bytes,
        line_count=total_lines,
        elapsed_seconds=elapsed,
        throughput_mib_per_sec=throughput,
        peak_memory_bytes=peak_memory_bytes,
    )


# ---------------------------------------------------------------------------
# CLI and entry point
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser."""

    parser = argparse.ArgumentParser(
        description="Stress-test streaming of a very large remote file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help="Optional JSON config file. CLI options override config values.",
    )
    parser.add_argument(
        "--mode",
        choices=("ssh", "local"),
        help="Stress-test a real SSH target or a local file without SSH.",
    )
    parser.add_argument("--host", help="SSH host to connect to.")
    parser.add_argument("--port", type=int, help="SSH port.")
    parser.add_argument("--username", help="SSH username.")
    parser.add_argument("--private-key-path", help="Path to the private key file.")
    parser.add_argument("--password", help="Password auth or private-key passphrase.")
    parser.add_argument(
        "--connect-timeout-seconds",
        type=float,
        help="TCP, banner, and auth timeout in seconds.",
    )
    parser.add_argument(
        "--keepalive-seconds",
        type=int,
        help="SSH keepalive interval in seconds; 0 disables keepalives.",
    )
    parser.add_argument("--known-hosts-path", help="Known-hosts path for strict verification.")
    parser.add_argument(
        "--allow-unknown-hosts",
        action="store_true",
        help="Accept unknown host keys automatically.",
    )
    parser.add_argument("--folder", help="Remote folder to search inside.")
    parser.add_argument("--filename", help="Remote filename or member-style target.")
    parser.add_argument("--local-path", type=Path, help="Local file path for local mode.")
    parser.add_argument(
        "--generate-local-file",
        action="store_true",
        help="Generate the local file in local mode if it does not already exist.",
    )
    parser.add_argument(
        "--size-gib",
        type=float,
        metavar="N",
        help="Approximate generated local file size in GiB for --generate-local-file.",
    )
    parser.add_argument(
        "--line-template",
        metavar="TEXT",
        help="Repeated line template used when generating a local file.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        metavar="BYTES",
        help="LineStreamer chunk size in bytes.",
    )
    parser.add_argument(
        "--max-line-bytes",
        type=int,
        metavar="BYTES",
        help="Maximum buffered line size in bytes.",
    )
    parser.add_argument("--encoding", help="Text decoding encoding.")
    parser.add_argument("--errors", help="Decode error handler.")
    parser.add_argument(
        "--track-memory",
        action="store_true",
        help="Track peak Python memory with tracemalloc.",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        metavar="PATH",
        help="Save the streaming results report as plain text to PATH.",
    )
    return parser


def main() -> int:
    """Entry point."""

    parser = build_arg_parser()
    args = parser.parse_args()
    config_data = load_config_file(args.config) if args.config is not None else {}

    mode = cast(str, resolve_value(args.mode, config_data, "mode", DEFAULT_MODE))
    if mode not in {"ssh", "local"}:
        raise SystemExit("mode must be either 'ssh' or 'local'")

    host = cast(str | None, resolve_value(args.host, config_data, "host", None))
    port = cast(int, resolve_value(args.port, config_data, "port", DEFAULT_PORT))
    username = cast(str | None, resolve_value(args.username, config_data, "username", None))
    private_key_path = cast(
        str | None,
        resolve_value(args.private_key_path, config_data, "private_key_path", None),
    )
    password = cast(str | None, resolve_value(args.password, config_data, "password", None))
    connect_timeout_seconds = float(
        resolve_value(
            args.connect_timeout_seconds,
            config_data,
            "connect_timeout_seconds",
            DEFAULT_CONNECT_TIMEOUT_SECONDS,
        )
    )
    keepalive_seconds = cast(
        int,
        resolve_value(
            args.keepalive_seconds,
            config_data,
            "keepalive_seconds",
            DEFAULT_KEEPALIVE_SECONDS,
        ),
    )
    known_hosts_path = cast(
        str | None,
        resolve_value(args.known_hosts_path, config_data, "known_hosts_path", None),
    )
    allow_unknown_hosts = resolve_bool(
        args.allow_unknown_hosts,
        config_data,
        "allow_unknown_hosts",
        False,
    )
    folder = cast(str | None, resolve_value(args.folder, config_data, "folder", None))
    filename = cast(str | None, resolve_value(args.filename, config_data, "filename", None))
    local_path = resolve_path(args.local_path, config_data, "local_path", DEFAULT_LOCAL_PATH)
    generate_local_file = resolve_bool(
        args.generate_local_file,
        config_data,
        "generate_local_file",
        False,
    )
    size_gib = float(resolve_value(args.size_gib, config_data, "size_gib", DEFAULT_SIZE_GIB))
    line_template = cast(
        str,
        resolve_value(args.line_template, config_data, "line_template", DEFAULT_LINE_TEMPLATE),
    )
    chunk_size = cast(
        int,
        resolve_value(args.chunk_size, config_data, "chunk_size", DEFAULT_CHUNK_SIZE),
    )
    max_line_bytes = cast(
        int,
        resolve_value(
            args.max_line_bytes,
            config_data,
            "max_line_bytes",
            DEFAULT_MAX_LINE_BYTES,
        ),
    )
    encoding = cast(str, resolve_value(args.encoding, config_data, "encoding", DEFAULT_ENCODING))
    errors = cast(str, resolve_value(args.errors, config_data, "errors", DEFAULT_ERRORS))
    track_memory = resolve_bool(args.track_memory, config_data, "track_memory", False)
    report_out = resolve_path(args.report_out, config_data, "report_out", None)

    if local_path is None:
        raise SystemExit("local_path could not be resolved")

    target_size_bytes = int(size_gib * GiB)

    ssh_config: SshConfig | None
    if mode == "ssh":
        if not host:
            raise SystemExit("--host is required in ssh mode")
        if not folder:
            raise SystemExit("--folder is required in ssh mode")
        if not filename:
            raise SystemExit("--filename is required in ssh mode")
        ssh_config = SshConfig(
            host=host,
            port=port,
            username=username,
            private_key_path=private_key_path,
            password=password,
            connect_timeout_seconds=connect_timeout_seconds,
            keepalive_seconds=keepalive_seconds,
            known_hosts_path=known_hosts_path,
            allow_unknown_hosts=allow_unknown_hosts,
        )
    else:
        ssh_config = None

    config = LineStreamerConfig(
        chunk_size=chunk_size,
        encoding=encoding,
        errors=errors,
        max_line_bytes=max_line_bytes,
    )

    if mode == "local" and generate_local_file and not local_path.exists():
        print("Generating large local file...")
        print("------------------------------")
        print(f"Local path:         {local_path}")
        print(f"Target size:        {size_gib:.2f} GiB decoded")
        generate_large_local_file(
            path=local_path,
            target_size_bytes=target_size_bytes,
            line_template=line_template,
            encoding=encoding,
        )
        print("Generation complete.")
        print()

    print("Streaming large target...")
    print("-------------------------")
    if mode == "ssh":
        assert ssh_config is not None
        assert folder is not None
        assert filename is not None
        result = stream_large_remote_file(
            folder=folder,
            filename=filename,
            ssh_config=ssh_config,
            config=config,
            track_memory=track_memory,
        )
    else:
        result = stream_large_local_file(
            local_path=local_path,
            config=config,
            track_memory=track_memory,
        )

    report = render_stress_report(result)
    print(report)

    if report_out is not None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        file_text = render_report_file(result, ssh_config, config, mode, timestamp)
        report_out.parent.mkdir(parents=True, exist_ok=True)
        report_out.write_text(file_text, encoding="utf-8")
        print(f"\nWrote report to: {report_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
