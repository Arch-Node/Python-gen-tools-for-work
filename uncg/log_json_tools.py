#!/usr/bin/env python3
"""Reusable JSON logging helpers for any Python script in this workspace.

This module is intentionally not tied to repoprep_lib so it can be used by
other tools and jobs. It supports:
  1) structured JSONL logging from live code
  2) conversion of plain text logs into JSONL events
"""

import datetime
import json
import logging
import os
import re
from typing import Any, Dict, Iterable, Optional

_REDACTION_PATTERNS = [
    # URL credential forms: https://token@host or https://user:pass@host
    re.compile(r"https?://[^\s/@:]+(?::[^\s/@]+)?@", re.IGNORECASE),
    # key/value style secrets
    re.compile(r"(?i)(password|passwd|token|secret)\s*[=:]\s*[^\s,;]+"),
]

_TEXT_LOG_LINE = re.compile(r"^\[(?P<ts>[^\]]+)\]\s*(?P<message>.*)$")


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format with trailing Z."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in _REDACTION_PATTERNS:
        redacted = pattern.sub("<redacted>", redacted)
    return redacted


def sanitize(value: Any) -> Any:
    """Recursively sanitize secrets in strings, dicts, lists, and tuples."""
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {str(k): sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, tuple):
        return tuple(sanitize(v) for v in value)
    return value


def make_event(
    *,
    level: str,
    message: str,
    app: str,
    component: str,
    run_id: Optional[str] = None,
    host: Optional[str] = None,
    **fields: Any,
) -> Dict[str, Any]:
    """Build a normalized JSON event dictionary."""
    event = {
        "timestamp": utc_now_iso(),
        "level": str(level).upper(),
        "app": app,
        "component": component,
        "message": sanitize(message),
        "run_id": run_id,
        "host": host or os.uname().nodename,
    }
    for key, value in fields.items():
        event[str(key)] = sanitize(value)
    return event


def write_jsonl_event(output_path: str, event: Dict[str, Any]) -> None:
    """Append one JSON object as a single line to output_path."""
    output_dir = os.path.dirname(os.path.abspath(output_path))
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True, default=str) + "\n")


class JsonLineLogger:
    """Simple structured JSONL logger usable without the logging module."""

    def __init__(
        self,
        *,
        output_path: str,
        app: str,
        component: str,
        run_id: Optional[str] = None,
        host: Optional[str] = None,
    ) -> None:
        self.output_path = output_path
        self.app = app
        self.component = component
        self.run_id = run_id
        self.host = host

    def log(self, level: str, message: str, **fields: Any) -> Dict[str, Any]:
        """Write one structured event and return the emitted dict."""
        event = make_event(
            level=level,
            message=message,
            app=self.app,
            component=self.component,
            run_id=self.run_id,
            host=self.host,
            **fields,
        )
        write_jsonl_event(self.output_path, event)
        return event


class JsonLineFormatter(logging.Formatter):
    """Python logging formatter that emits one JSON object per log record."""

    def __init__(self, *, app: str, component: str, run_id: Optional[str] = None) -> None:
        super().__init__()
        self.app = app
        self.component = component
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        base_fields = {
            "logger": record.name,
            "module": record.module,
            "func_name": record.funcName,
            "line_no": record.lineno,
        }
        if record.exc_info:
            base_fields["exception"] = self.formatException(record.exc_info)

        event = make_event(
            level=record.levelname,
            message=record.getMessage(),
            app=self.app,
            component=self.component,
            run_id=self.run_id,
            **base_fields,
        )
        return json.dumps(event, ensure_ascii=True, default=str)


def configure_json_file_handler(
    *,
    logger: logging.Logger,
    output_path: str,
    app: str,
    component: str,
    run_id: Optional[str] = None,
    level: int = logging.INFO,
) -> logging.Handler:
    """Attach a JSONL file handler to an existing logger and return the handler."""
    output_dir = os.path.dirname(os.path.abspath(output_path))
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    handler = logging.FileHandler(output_path, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(JsonLineFormatter(app=app, component=component, run_id=run_id))
    logger.addHandler(handler)
    return handler


def parse_text_log_line(line: str) -> Dict[str, Any]:
    """Parse one plain log line into a best-effort structured record."""
    stripped = line.rstrip("\n")
    match = _TEXT_LOG_LINE.match(stripped)

    if match:
        raw_message = match.group("message")
        timestamp_text = match.group("ts")
    else:
        raw_message = stripped
        timestamp_text = None

    level = "INFO"
    message = raw_message
    if raw_message.startswith("ERROR:"):
        level = "ERROR"
    elif raw_message.startswith("WARN:") or raw_message.startswith("WARNING:"):
        level = "WARNING"
    elif raw_message.startswith("DEBUG:"):
        level = "DEBUG"

    if ":" in raw_message and raw_message.split(":", 1)[0] in {"ERROR", "WARN", "WARNING", "DEBUG"}:
        message = raw_message.split(":", 1)[1].strip()

    return {
        "timestamp_text": timestamp_text,
        "level": level,
        "message": sanitize(message),
        "raw": sanitize(stripped),
    }


def convert_text_log_to_jsonl(
    *,
    input_path: str,
    output_path: str,
    app: str,
    component: str,
    run_id: Optional[str] = None,
) -> int:
    """Convert a text log file into JSONL records. Returns number of lines converted."""
    converted = 0
    with open(input_path, "r", encoding="utf-8") as source:
        for line in source:
            parsed = parse_text_log_line(line)
            event = make_event(
                level=parsed["level"],
                message=parsed["message"],
                app=app,
                component=component,
                run_id=run_id,
                source_file=input_path,
                source_timestamp=parsed["timestamp_text"],
                raw=parsed["raw"],
            )
            write_jsonl_event(output_path, event)
            converted += 1
    return converted
