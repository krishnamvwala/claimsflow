"""Structured logging helpers that exclude record payloads by design."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    """Render a small allowlisted JSON log envelope."""

    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in (
            "environment_id",
            "run_id",
            "task_id",
            "batch_id",
            "publication_id",
            "rule_id",
            "code_version",
        ):
            value = getattr(record, field, None)
            if value is not None:
                event[field] = str(value)
        return json.dumps(event, sort_keys=True)


def configure_json_logging(level: str = "INFO") -> None:
    """Configure the root logger with one structured standard-output handler."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
