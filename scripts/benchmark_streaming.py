#!/usr/bin/env python3
"""
scripts.benchmark_streaming
===========================

Performance benchmark for ``ssh_logstream.LineStreamer``.

Overview
--------
Benchmarks end-to-end remote streaming performance across one or more real
remote files exposed over SSH, covering the full pipeline:

    remote file discovery -> SSH byte stream -> decode -> line emission

It can also run in a local benchmarking mode that feeds bytes from local files
through the same decoding and line-emission pipeline without requiring an SSH
server.

The script supports an optional JSON configuration file so benchmark settings
can be edited once and reused across later runs. CLI arguments always override
config file values.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
import tracemalloc
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ssh_logstream import LineStreamer, LineStreamerConfig, SshConfig
from ssh_logstream.streaming import LineStreamerCore

MiB = 1024 * 1024
DEFAULT_MODE = "ssh"
DEFAULT_PORT = 22
DEFAULT_CONNECT_TIMEOUT_SECONDS = 30.0
DEFAULT_KEEPALIVE_SECONDS = 10
DEFAULT_WORKSPACE = Path(".benchmarks/local-fixtures")
DEFAULT_REPEAT = 3
DEFAULT_CHUNK_SIZE = 1 << 20
DEFAULT_MAX_LINE_BYTES = 32 * (1 << 20)
DEFAULT_ENCODING = "utf-8"
DEFAULT_ERRORS = "replace"


# ---------------------------------------------------------------------------
# Benchmark case definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """Definition of one benchmark scenario."""

    name: str
    target: str
    description: str


def build_many_short_lines() -> str:
    """High line-count, short LF-terminated log lines."""

    return "INFO request completed status=200 latency_ms=12 path=/healthcheck\n" * 200_000


def build_medium_lines() -> str:
    """Structured medium-width log lines with realistic field payloads."""

    lines: list[str] = []
    for index in range(80_000):
        lines.append(
            f"2026-03-20T12:00:{index % 60:02d}Z "
            f"service=api level=INFO req_id={index:08d} "
            f"user_id={index % 10000:05d} method=GET path=/v1/resource/{index % 250} "
            f"status=200 latency_ms={(index % 47) + 3} region=us-east-1\n"
        )
    return "".join(lines)


def build_crlf_lines() -> str:
    """Windows-style CRLF-terminated lines."""

    return "INFO windows-style log line with CRLF ending\r\n" * 150_000


def build_large_final_partial_line() -> str:
    """Many normal lines followed by a large final unterminated tail."""

    head = "INFO normal line before final partial tail\n" * 100_000
    tail = "TAIL" * (MiB // 4)
    return head + tail


DEFAULT_LOCAL_CASE_FACTORIES: tuple[tuple[str, str, str, Any], ...] = (
    (
        "many-short-lines",
        "many_short_lines.log",
        "High line-count case with short LF-terminated log lines.",
        build_many_short_lines,
    ),
    (
        "medium-lines",
        "medium_lines.log",
        "Structured medium-width log lines with realistic field payloads.",
        build_medium_lines,
    ),
    (
        "crlf-lines",
        "crlf_lines.log",
        "Windows-style CRLF line endings through the decoding pipeline.",
        build_crlf_lines,
    ),
    (
        "large-final-partial-line",
        "large_final_partial_line.log",
        "Many normal lines followed by a large final partial line.",
        build_large_final_partial_line,
    ),
)


# ---------------------------------------------------------------------------
# Metrics dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunMetrics:
    """Metrics collected from one timed benchmark run."""

    case_name: str
    run_index: int
    duration_seconds: float
    line_count: int
    decoded_bytes: int
    throughput_mib_per_sec: float
    lines_per_sec: float
    peak_memory_bytes: int | None


@dataclass(frozen=True, slots=True)
class CaseSummary:
    """Aggregate metrics across repeated runs for one benchmark case."""

    case_name: str
    description: str
    repeats: int
    line_count: int
    decoded_bytes: int
    mean_duration_seconds: float
    median_duration_seconds: float
    min_duration_seconds: float
    max_duration_seconds: float
    mean_throughput_mib_per_sec: float
    median_throughput_mib_per_sec: float
    mean_lines_per_sec: float
    median_lines_per_sec: float
    peak_memory_bytes_max: int | None


# ---------------------------------------------------------------------------
# Configuration file support
# ---------------------------------------------------------------------------


def load_config_file(path: Path) -> dict[str, Any]:
    """Load one JSON benchmark config file."""

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


def resolve_string_list(
    cli_values: list[str] | None,
    config_data: dict[str, Any],
    key: str,
) -> list[str] | None:
    """Resolve one repeated string option with CLI precedence."""

    if cli_values:
        return cli_values
    raw_value = config_data.get(key)
    if raw_value is None:
        return None
    if not isinstance(raw_value, list) or not all(isinstance(item, str) for item in raw_value):
        raise SystemExit(f"Config key {key!r} must be an array of strings")
    return list(raw_value)


# ---------------------------------------------------------------------------
# Benchmark execution
# ---------------------------------------------------------------------------


def run_single_benchmark(
    *,
    folder: str,
    case: BenchmarkCase,
    ssh_config: SshConfig,
    config: LineStreamerConfig,
    track_memory: bool,
    run_index: int,
) -> RunMetrics:
    """Run one timed benchmark iteration and return its metrics."""

    if track_memory:
        tracemalloc.start()

    started = time.perf_counter()
    line_count = 0
    decoded_bytes = 0

    streamer = LineStreamer(
        folder=folder,
        filename=case.target,
        ssh_config=ssh_config,
        config=config,
    )
    for line in streamer.stream():
        line_count += 1
        decoded_bytes += len(line.encode(config.encoding, errors=config.errors))

    duration = time.perf_counter() - started

    peak_memory_bytes: int | None
    if track_memory:
        _, peak_memory_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    else:
        peak_memory_bytes = None

    throughput_mib_per_sec = (decoded_bytes / MiB) / duration if duration > 0 else math.inf
    lines_per_sec = line_count / duration if duration > 0 else math.inf

    return RunMetrics(
        case_name=case.name,
        run_index=run_index,
        duration_seconds=duration,
        line_count=line_count,
        decoded_bytes=decoded_bytes,
        throughput_mib_per_sec=throughput_mib_per_sec,
        lines_per_sec=lines_per_sec,
        peak_memory_bytes=peak_memory_bytes,
    )


def run_single_local_benchmark(
    *,
    case: BenchmarkCase,
    config: LineStreamerConfig,
    track_memory: bool,
    run_index: int,
    decoded_bytes: int,
) -> RunMetrics:
    """Run one timed benchmark iteration against a local file."""

    path = Path(case.target)
    if track_memory:
        tracemalloc.start()

    started = time.perf_counter()
    line_count = 0
    core = LineStreamerCore(config)

    with path.open("rb") as handle:
        def chunks() -> Iterator[bytes]:
            while True:
                chunk = handle.read(config.chunk_size)
                if not chunk:
                    return
                yield chunk

        for _line in core.iter_text(chunks()):
            line_count += 1

    duration = time.perf_counter() - started

    peak_memory_bytes: int | None
    if track_memory:
        _, peak_memory_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    else:
        peak_memory_bytes = None

    throughput_mib_per_sec = (decoded_bytes / MiB) / duration if duration > 0 else math.inf
    lines_per_sec = line_count / duration if duration > 0 else math.inf

    return RunMetrics(
        case_name=case.name,
        run_index=run_index,
        duration_seconds=duration,
        line_count=line_count,
        decoded_bytes=decoded_bytes,
        throughput_mib_per_sec=throughput_mib_per_sec,
        lines_per_sec=lines_per_sec,
        peak_memory_bytes=peak_memory_bytes,
    )


def measure_local_case(path: Path, config: LineStreamerConfig) -> tuple[int, int]:
    """Measure decoded bytes and line count once outside the timed benchmark loop."""

    core = LineStreamerCore(config)
    line_count = 0
    decoded_bytes = 0

    with path.open("rb") as handle:
        def chunks() -> Iterator[bytes]:
            while True:
                chunk = handle.read(config.chunk_size)
                if not chunk:
                    return
                yield chunk

        for line in core.iter_text(chunks()):
            line_count += 1
            decoded_bytes += len(line.encode(config.encoding, errors=config.errors))

    return line_count, decoded_bytes


def summarize_case(case: BenchmarkCase, runs: list[RunMetrics]) -> CaseSummary:
    """Aggregate repeated run metrics into one summary for a benchmark case."""

    durations = [run.duration_seconds for run in runs]
    throughputs = [run.throughput_mib_per_sec for run in runs]
    line_rates = [run.lines_per_sec for run in runs]
    peak_values = [run.peak_memory_bytes for run in runs if run.peak_memory_bytes is not None]

    first = runs[0]
    return CaseSummary(
        case_name=case.name,
        description=case.description,
        repeats=len(runs),
        line_count=first.line_count,
        decoded_bytes=first.decoded_bytes,
        mean_duration_seconds=statistics.mean(durations),
        median_duration_seconds=statistics.median(durations),
        min_duration_seconds=min(durations),
        max_duration_seconds=max(durations),
        mean_throughput_mib_per_sec=statistics.mean(throughputs),
        median_throughput_mib_per_sec=statistics.median(throughputs),
        mean_lines_per_sec=statistics.mean(line_rates),
        median_lines_per_sec=statistics.median(line_rates),
        peak_memory_bytes_max=max(peak_values) if peak_values else None,
    )


def create_local_fixture(path: Path, text: str, encoding: str) -> None:
    """Write one local text fixture to disk."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding, newline="")


def prepare_default_local_cases(workspace: Path, encoding: str) -> list[BenchmarkCase]:
    """Create reusable local benchmark fixtures and return matching case specs."""

    cases: list[BenchmarkCase] = []
    for name, filename, description, factory in DEFAULT_LOCAL_CASE_FACTORIES:
        path = workspace / filename
        if not path.exists():
            create_local_fixture(path, factory(), encoding)
        cases.append(BenchmarkCase(name=name, target=str(path), description=description))
    return cases


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_bytes(num_bytes: int | None) -> str:
    """Format a byte count as a human-readable string."""

    if num_bytes is None:
        return "-"
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < MiB:
        return f"{num_bytes / 1024:.1f} KiB"
    return f"{num_bytes / MiB:.2f} MiB"


def format_run_metrics(metrics: RunMetrics) -> str:
    """Format one run's metrics as a compact single-line string."""

    return (
        f"  run {metrics.run_index + 1:>2}: "
        f"{metrics.duration_seconds:8.4f} s | "
        f"{metrics.decoded_bytes / MiB:8.2f} MiB | "
        f"{metrics.line_count:>10,d} lines | "
        f"{metrics.throughput_mib_per_sec:8.2f} MiB/s | "
        f"{metrics.lines_per_sec:10,.0f} lines/s | "
        f"peak mem {format_bytes(metrics.peak_memory_bytes)}"
    )


_COL_CASE = 24
_COL_MIB = 10
_COL_LINES = 12
_COL_MEAN_S = 10
_COL_MED_S = 10
_COL_MEAN_MIB = 12
_COL_MED_MIB = 14
_COL_MEAN_LPS = 14
_COL_PEAK = 12
_TABLE_WIDTH = (
    _COL_CASE + 1 + _COL_MIB + 1 + _COL_LINES + 1 + _COL_MEAN_S + 1
    + _COL_MED_S + 1 + _COL_MEAN_MIB + 1 + _COL_MED_MIB + 1
    + _COL_MEAN_LPS + 1 + _COL_PEAK
)


def render_summary_table(summaries: list[CaseSummary]) -> str:
    """Render the benchmark summary table as a multi-line string."""

    if not summaries:
        return ""

    sep = "=" * _TABLE_WIDTH
    thin = "-" * _TABLE_WIDTH
    header = (
        f"{'case':<{_COL_CASE}} "
        f"{'MiB':>{_COL_MIB}} "
        f"{'lines':>{_COL_LINES}} "
        f"{'mean s':>{_COL_MEAN_S}} "
        f"{'median s':>{_COL_MED_S}} "
        f"{'mean MiB/s':>{_COL_MEAN_MIB}} "
        f"{'median MiB/s':>{_COL_MED_MIB}} "
        f"{'mean lines/s':>{_COL_MEAN_LPS}} "
        f"{'peak mem':>{_COL_PEAK}}"
    )

    lines = ["", sep, header, thin]
    for row in summaries:
        lines.append(
            f"{row.case_name:<{_COL_CASE}} "
            f"{row.decoded_bytes / MiB:>{_COL_MIB}.2f} "
            f"{row.line_count:>{_COL_LINES},d} "
            f"{row.mean_duration_seconds:>{_COL_MEAN_S}.4f} "
            f"{row.median_duration_seconds:>{_COL_MED_S}.4f} "
            f"{row.mean_throughput_mib_per_sec:>{_COL_MEAN_MIB}.2f} "
            f"{row.median_throughput_mib_per_sec:>{_COL_MED_MIB}.2f} "
            f"{row.mean_lines_per_sec:>{_COL_MEAN_LPS},.0f} "
            f"{format_bytes(row.peak_memory_bytes_max):>{_COL_PEAK}}"
        )
    lines.append(sep)
    return "\n".join(lines)


def render_table_file(
    summaries: list[CaseSummary],
    ssh_config: SshConfig | None,
    config: LineStreamerConfig,
    folder: str | None,
    mode: str,
    repeats: int,
    timestamp: str,
) -> str:
    """Render the summary table with a config header for saving to a file."""

    header_lines = [
        "ssh-logstream Benchmark Results",
        "=" * 31,
        f"Run at:                  {timestamp}",
        f"mode:                    {mode}",
        f"chunk_size:              {config.chunk_size:,} bytes",
        f"max_line_bytes:          {config.max_line_bytes:,} bytes",
        f"encoding:                {config.encoding}",
        f"errors:                  {config.errors}",
        f"repeats:                 {repeats}",
    ]
    if ssh_config is not None:
        header_lines.extend(
            [
                f"host:                    {ssh_config.host}",
                f"folder:                  {folder}",
                f"connect_timeout_seconds: {ssh_config.connect_timeout_seconds}",
                f"keepalive_seconds:       {ssh_config.keepalive_seconds}",
            ]
        )
    return "\n".join(header_lines) + render_summary_table(summaries) + "\n"


# ---------------------------------------------------------------------------
# Progress output helpers
# ---------------------------------------------------------------------------


def print_case_header(case: BenchmarkCase, file: IO[str] = sys.stdout) -> None:
    """Print a readable heading for one benchmark case."""

    print(file=file)
    print(f"[{case.name}]", file=file)
    print(case.description, file=file)


def print_run_metrics(metrics: RunMetrics, file: IO[str] = sys.stdout) -> None:
    """Print one run's metrics to *file*."""

    print(format_run_metrics(metrics), file=file)


# ---------------------------------------------------------------------------
# CLI and entry point
# ---------------------------------------------------------------------------


def parse_case_spec(spec: str) -> BenchmarkCase:
    """Parse one ``NAME=TARGET`` benchmark case specification."""

    if "=" not in spec:
        raise SystemExit(f"Invalid case spec {spec!r}; expected NAME=TARGET")
    name, target = spec.split("=", 1)
    case_name = name.strip()
    case_target = target.strip()
    if not case_name or not case_target:
        raise SystemExit(f"Invalid case spec {spec!r}; expected NAME=TARGET")
    return BenchmarkCase(
        name=case_name,
        target=case_target,
        description=f"Streaming target {case_target!r}.",
    )


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser."""

    parser = argparse.ArgumentParser(
        description="Benchmark end-to-end remote file streaming with ssh-logstream.",
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
        help="Benchmark over a real SSH target or local files without SSH.",
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
    parser.add_argument(
        "--case-spec",
        action="append",
        dest="case_specs",
        metavar="NAME=FILENAME",
        help="SSH benchmark case specification. May be repeated.",
    )
    parser.add_argument(
        "--local-case-spec",
        action="append",
        dest="local_case_specs",
        metavar="NAME=PATH",
        help="Local benchmark case specification. May be repeated.",
    )
    parser.add_argument(
        "--generate-local-fixtures",
        action="store_true",
        help="Generate default local text fixtures under --workspace for local mode.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        metavar="DIR",
        help="Workspace directory used for generated local benchmark fixtures.",
    )
    parser.add_argument("--repeat", type=int, metavar="N", help="Timed runs per case.")
    parser.add_argument(
        "--chunk-size",
        type=int,
        metavar="BYTES",
        help="LineStreamerConfig.chunk_size in bytes.",
    )
    parser.add_argument(
        "--max-line-bytes",
        type=int,
        metavar="BYTES",
        help="LineStreamerConfig.max_line_bytes in bytes.",
    )
    parser.add_argument("--encoding", help="Text decoding encoding.")
    parser.add_argument("--errors", help="Decode error handler.")
    parser.add_argument(
        "--track-memory",
        action="store_true",
        help="Track peak Python memory with tracemalloc.",
    )
    parser.add_argument(
        "--table-out",
        type=Path,
        metavar="PATH",
        help="Save the summary table as plain text to PATH.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        metavar="PATH",
        help="Save full per-run benchmark data as JSON to PATH.",
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
    case_specs = resolve_string_list(args.case_specs, config_data, "case_specs")
    local_case_specs = resolve_string_list(args.local_case_specs, config_data, "local_case_specs")
    generate_local_fixtures = resolve_bool(
        args.generate_local_fixtures,
        config_data,
        "generate_local_fixtures",
        False,
    )
    workspace = resolve_path(args.workspace, config_data, "workspace", DEFAULT_WORKSPACE)
    repeat = cast(int, resolve_value(args.repeat, config_data, "repeat", DEFAULT_REPEAT))
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
    table_out = resolve_path(args.table_out, config_data, "table_out", None)
    json_out = resolve_path(args.json_out, config_data, "json_out", None)

    if repeat <= 0:
        raise SystemExit("--repeat must be greater than 0")
    if workspace is None:
        raise SystemExit("workspace could not be resolved")

    ssh_config: SshConfig | None
    if mode == "ssh":
        if not case_specs:
            raise SystemExit("At least one --case-spec NAME=FILENAME must be provided in ssh mode")
        if not host:
            raise SystemExit("--host is required in ssh mode")
        if not folder:
            raise SystemExit("--folder is required in ssh mode")
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
        cases = [parse_case_spec(spec) for spec in case_specs]
    else:
        if generate_local_fixtures:
            cases = prepare_default_local_cases(workspace, encoding)
        elif local_case_specs:
            cases = [parse_case_spec(spec) for spec in local_case_specs]
        else:
            raise SystemExit(
                "In local mode, provide --local-case-spec NAME=PATH or use --generate-local-fixtures"
            )
        ssh_config = None

    config = LineStreamerConfig(
        chunk_size=chunk_size,
        encoding=encoding,
        errors=errors,
        max_line_bytes=max_line_bytes,
    )

    json_payload: dict[str, object] = {
        "mode": mode,
        "stream_config": {
            "chunk_size": config.chunk_size,
            "encoding": config.encoding,
            "errors": config.errors,
            "max_line_bytes": config.max_line_bytes,
        },
        "cases": [],
    }
    if mode == "local":
        json_payload["workspace"] = str(workspace)
    if ssh_config is not None:
        json_payload["ssh_config"] = {
            "host": ssh_config.host,
            "port": ssh_config.port,
            "username": ssh_config.username,
            "connect_timeout_seconds": ssh_config.connect_timeout_seconds,
            "keepalive_seconds": ssh_config.keepalive_seconds,
            "known_hosts_path": ssh_config.known_hosts_path,
            "allow_unknown_hosts": ssh_config.allow_unknown_hosts,
        }
        json_payload["folder"] = folder

    summaries: list[CaseSummary] = []
    for case in cases:
        print_case_header(case)
        runs: list[RunMetrics] = []
        local_line_count: int | None = None
        local_decoded_bytes: int | None = None
        if mode == "local":
            local_line_count, local_decoded_bytes = measure_local_case(Path(case.target), config)
        for run_index in range(repeat):
            if mode == "ssh":
                assert ssh_config is not None
                assert folder is not None
                metrics = run_single_benchmark(
                    folder=folder,
                    case=case,
                    ssh_config=ssh_config,
                    config=config,
                    track_memory=track_memory,
                    run_index=run_index,
                )
            else:
                assert local_decoded_bytes is not None
                metrics = run_single_local_benchmark(
                    case=case,
                    config=config,
                    track_memory=track_memory,
                    run_index=run_index,
                    decoded_bytes=local_decoded_bytes,
                )
                if local_line_count is not None and metrics.line_count != local_line_count:
                    raise RuntimeError("Local benchmark line count changed between measurement passes.")
            runs.append(metrics)
            print_run_metrics(metrics)

        summary = summarize_case(case, runs)
        summaries.append(summary)
        case_payload = {
            "case": asdict(case),
            "runs": [asdict(run) for run in runs],
            "summary": asdict(summary),
        }
        case_list = cast(list[object], json_payload["cases"])
        case_list.append(case_payload)

    table_text = render_summary_table(summaries)
    print(table_text)

    if table_out is not None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        file_text = render_table_file(
            summaries=summaries,
            ssh_config=ssh_config,
            config=config,
            folder=folder,
            mode=mode,
            repeats=repeat,
            timestamp=timestamp,
        )
        table_out.parent.mkdir(parents=True, exist_ok=True)
        table_out.write_text(file_text, encoding="utf-8")
        print(f"\nWrote table to: {table_out}")

    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")
        print(f"Wrote JSON to:  {json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
