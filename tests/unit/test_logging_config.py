from __future__ import annotations

import json
import logging

from claimsflow.logging_config import JsonFormatter


def test_json_formatter_uses_allowlisted_context_only() -> None:
    record = logging.LogRecord(
        name="claimsflow.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="batch registered",
        args=(),
        exc_info=None,
    )
    record.batch_id = "batch-001"
    record.claim_payload = "must-not-appear"

    event = json.loads(JsonFormatter().format(record))

    assert event["batch_id"] == "batch-001"
    assert event["message"] == "batch registered"
    assert "claim_payload" not in event
