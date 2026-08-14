from __future__ import annotations

import json
from io import StringIO

from claimsflow.cli import main


def test_doctor_prints_only_safe_configuration() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        ["doctor"],
        {
            "CLAIMSFLOW_ENVIRONMENT": "local",
            "CLAIMSFLOW_SYNTHETIC_ONLY": "true",
        },
        stdout,
        stderr,
    )

    result = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert result["status"] == "ok"
    assert result["synthetic_only"] is True
    assert "gcp_project" not in result


def test_doctor_reports_boundary_failure_without_traceback() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        ["doctor"],
        {"CLAIMSFLOW_SYNTHETIC_ONLY": "false"},
        stdout,
        stderr,
    )

    result = json.loads(stderr.getvalue())
    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert result["status"] == "error"
    assert "real data is prohibited" in result["reason"]
