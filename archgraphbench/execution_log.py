"""Observable algorithm execution, independent of all scientific calculations.

INFO describes phases and important decisions; DEBUG adds individual joins,
paths and synthetic cases. Events are emitted where decisions are computed,
not reconstructed afterward from the result tables. Importing this module is
silent: CLI entry points explicitly open a per-run logging session.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Iterator, TextIO

_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("agb_log_context", default={})
_SESSION = None


def _nonnegative_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("Use a finite number greater than or equal to zero")
    return number


def _nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("Use zero (unlimited) or a positive integer")
    return number


def add_logging_arguments(parser: argparse.ArgumentParser) -> None:
    """Keep the same demo controls on the runner, processor and builder."""
    group = parser.add_argument_group("live execution logging")
    group.add_argument("--verbose", action="store_true", help="Show phases, query answers and calculated metrics live")
    group.add_argument("--trace", action="store_true", help="Also show DEBUG joins, paths, and individual decisions")
    group.add_argument("--demo", action="store_true", help="Show numbered algorithm checkpoints (implies --verbose)")
    group.add_argument("--pause", action="store_true", help="Press Enter at checkpoints; needs interactive stdin; implies --demo")
    group.add_argument("--step-delay", type=_nonnegative_float, default=0.0,
                       help="Seconds to wait at each checkpoint; no delay by default; implies --demo")
    group.add_argument("--trace-limit", type=_nonnegative_int, default=50,
                       help="DEBUG records per event/context; 0 means all (default: 50)")


def validate_logging_arguments(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.pause and not sys.stdin.isatty():
        parser.error("--pause needs an interactive terminal; omit it for redirected/automated runs")


def forwarded_arguments(args: argparse.Namespace) -> list[str]:
    """Forward user controls to the child doing the actual work."""
    flags = [flag for attr, flag in [("verbose", "--verbose"), ("trace", "--trace"),
             ("demo", "--demo"), ("pause", "--pause")] if getattr(args, attr, False)]
    if args.step_delay:
        flags += ["--step-delay", str(args.step_delay)]
    flags += ["--trace-limit", str(args.trace_limit)]
    return flags


def _plain(value: Any) -> Any:
    """Make log fields JSON-safe without altering the algorithm's objects."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return [_plain(v) for v in sorted(value, key=str)]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = record.agb_event
        context = " ".join(f"{key}={value}" for key, value in event["context"].items())
        title = f"[{event['sequence']:04d} {event['level']}] {event['stage']} / {event['action']}"
        if context:
            title += " | " + context
        text = title + " | " + event["message"]
        if event["fields"]:
            # Keep terminal rows legible. The JSONL file retains full event fields.
            parts = []
            for key, value in event["fields"].items():
                value = json.dumps(value, ensure_ascii=True, allow_nan=False)
                parts.append(f"{key}={value[:237] + '...' if len(value) > 240 else value}")
            text += " | " + "; ".join(parts)
        if event.get("exception"):
            text += "\n" + event["exception"]
        return text


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(record.agb_event, ensure_ascii=True, allow_nan=False)


class ExecutionLog:
    """One process/session owns its own text log and line-delimited JSON log.

    `close()` must precede output-manifest hashing. Otherwise the log would
    change after its digest was recorded. Library calls never configure sinks.
    """
    def __init__(self, args: argparse.Namespace, *, directory: Path | None,
                 name: str = "algorithm", stream: TextIO | None = None,
                 interactive: bool = True):
        self.name = name
        self.started = time.monotonic()
        self.sequence = 0
        self.step = 0
        self.trace = args.trace
        self.demo = args.demo or args.pause or args.step_delay > 0
        self.pause = args.pause and interactive
        self.delay = args.step_delay if interactive else 0.0
        self.limit = args.trace_limit
        self.console_enabled = args.verbose or args.trace or self.demo
        self.counts: Counter = Counter()
        self.suppressed: Counter = Counter()
        self.closed = False
        self.lock = threading.RLock()
        self.logger = logging.Logger("archgraphbench." + name, level=logging.DEBUG if self.trace else logging.INFO)
        self.logger.propagate = False
        self.memory: list[dict] | None = [] if directory is None else None
        if directory is not None:
            self._file_handlers(directory)
        if self.console_enabled:
            handler = logging.StreamHandler(stream or sys.stdout)
            handler.setFormatter(_TextFormatter())
            self.logger.addHandler(handler)

    def _file_handlers(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for extension, formatter in (("log", _TextFormatter()), ("jsonl", _JsonFormatter())):
            handler = logging.FileHandler(directory / f"{self.name}.{extension}", mode="w", encoding="utf-8")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def attach_files(self, directory: Path) -> None:
        """Flush buffered builder events only after its safe output is created.

        The builder intentionally rejects nonempty output directories, so its
        logging must not pre-create files in that directory before calculation.
        """
        if self.memory is None:
            raise RuntimeError("Log files already attached")
        directory.mkdir(parents=True, exist_ok=True)
        text_formatter = _TextFormatter()
        with (directory / f"{self.name}.log").open("w", encoding="utf-8") as text, \
             (directory / f"{self.name}.jsonl").open("w", encoding="utf-8") as structured:
            for event in self.memory:
                record = logging.LogRecord(self.logger.name, logging.INFO, "", 0, event["message"], (), None)
                record.agb_event = event
                text.write(text_formatter.format(record) + "\n")
                structured.write(json.dumps(event, ensure_ascii=True, allow_nan=False) + "\n")
        for extension, formatter in (("log", _TextFormatter()), ("jsonl", _JsonFormatter())):
            handler = logging.FileHandler(directory / f"{self.name}.{extension}", mode="a", encoding="utf-8")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        self.memory = None

    def emit(self, level: int, stage: str, action: str, message: str, **fields: Any) -> None:
        if self.closed or not self.logger.isEnabledFor(level):
            return
        with self.lock:
            context = _plain(_CONTEXT.get())
            key = (stage, action, json.dumps(context, sort_keys=True))
            if level == logging.DEBUG:
                self.counts[key] += 1
                if self.limit and self.counts[key] > self.limit:
                    self.suppressed[key] += 1
                    if self.counts[key] == self.limit + 1:
                        self.emit(logging.INFO, stage, "TRACE_LIMIT", "Further DEBUG records in this event/context are omitted; processing continues.",
                                  event=action, limit=self.limit, unlimited_option="--trace-limit 0")
                    return
            self.sequence += 1
            event = {"session": self.name, "sequence": self.sequence,
                     "time_utc": datetime.now(timezone.utc).isoformat(),
                     "elapsed_seconds": round(time.monotonic() - self.started, 6),
                     "level": logging.getLevelName(level), "stage": stage,
                     "action": action, "message": message, "context": context,
                     "fields": _plain(fields)}
            if self.memory is not None:
                self.memory.append(event)
            self.logger.log(level, message, extra={"agb_event": event})

    def checkpoint(self, stage: str, message: str, **fields: Any) -> None:
        self.step += 1
        self.emit(logging.INFO, stage, f"STEP {self.step:02d}", message, **fields)
        if self.pause:
            # A newline is deliberate: the parent can stream this prompt through
            # its pipe before the child waits for Enter on inherited stdin.
            print("    DEMO: Press Enter to execute this step (Ctrl+C to stop).", flush=True)
            if sys.stdin.readline() == "":
                raise EOFError("Demo input closed; rerun without --pause")
        elif self.delay:
            time.sleep(self.delay)

    def close(self) -> None:
        if self.closed:
            return
        for (stage, action, context), count in sorted(self.suppressed.items()):
            self.emit(logging.INFO, stage, "TRACE_SUMMARY", "DEBUG detail omitted by the display limit, not by the algorithm.",
                      event=action, omitted=count, event_context=json.loads(context))
        for handler in list(self.logger.handlers):
            handler.flush()
            handler.close()
            self.logger.removeHandler(handler)
        self.closed = True


def configure(args: argparse.Namespace, directory: Path | None, *, name="algorithm",
              stream: TextIO | None = None, interactive: bool = True) -> ExecutionLog:
    global _SESSION
    if _SESSION is not None and not _SESSION.closed:
        _SESSION.close()
    _SESSION = ExecutionLog(args, directory=directory, name=name, stream=stream, interactive=interactive)
    return _SESSION


@contextmanager
def context(**fields: Any) -> Iterator[None]:
    token = _CONTEXT.set({**_CONTEXT.get(), **fields})
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def info(stage: str, action: str, message: str, **fields: Any) -> None:
    if _SESSION is not None:
        _SESSION.emit(logging.INFO, stage, action, message, **fields)


def debug(stage: str, action: str, message: str, **fields: Any) -> None:
    if _SESSION is not None:
        _SESSION.emit(logging.DEBUG, stage, action, message, **fields)


def warning(stage: str, action: str, message: str, **fields: Any) -> None:
    if _SESSION is not None:
        _SESSION.emit(logging.WARNING, stage, action, message, **fields)


def error(stage: str, action: str, message: str, **fields: Any) -> None:
    if _SESSION is not None:
        _SESSION.emit(logging.ERROR, stage, action, message, **fields)


def checkpoint(stage: str, message: str, **fields: Any) -> None:
    if _SESSION is not None:
        _SESSION.checkpoint(stage, message, **fields)


def stream_child(command: list[str], stdout_path: Path, stderr_path: Path, *, echo: bool) -> tuple[int, str, str]:
    """Tee both pipes while the child runs; do not wait for a completed study.

    Separate reader threads prevent a full stderr pipe from deadlocking stdout.
    Stdin is inherited so --pause works from an actual interactive terminal.
    """
    for path in (stdout_path, stderr_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    tails = {"stdout": "", "stderr": ""}
    failures = []
    with stdout_path.open("w", encoding="utf-8") as stdout_file, \
         stderr_path.open("w", encoding="utf-8") as stderr_file:
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, encoding="utf-8", errors="replace", bufsize=1)

        def pump(pipe, file, terminal, key):
            try:
                for line in pipe:
                    file.write(line)
                    file.flush()
                    tails[key] = (tails[key] + line)[-4000:]
                    if echo:
                        terminal.write(line)
                        terminal.flush()
            except Exception as exc:
                failures.append(exc)
            finally:
                pipe.close()

        threads = [threading.Thread(target=pump, args=(child.stdout, stdout_file, sys.stdout, "stdout")),
                   threading.Thread(target=pump, args=(child.stderr, stderr_file, sys.stderr, "stderr"))]
        for thread in threads:
            thread.start()
        try:
            code = child.wait()
        except BaseException:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            raise
        finally:
            for thread in threads:
                thread.join()
        if failures:
            raise OSError("Could not stream child output") from failures[0]
    return code, tails["stdout"], tails["stderr"]
