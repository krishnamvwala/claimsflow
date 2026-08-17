from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from claimsflow.cli import main
from claimsflow.generator import GenerationConfig, generate_delivery

ROOT = Path(__file__).resolve().parents[2]


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


def test_generate_creates_a_safe_manifest_and_summary(tmp_path: Path) -> None:
    stdout = StringIO()
    stderr = StringIO()
    output = tmp_path / "delivery"

    exit_code = main(
        [
            "generate",
            "--service-month",
            "2026-07",
            "--claims",
            "16",
            "--seed",
            "42",
            "--output",
            str(output),
        ],
        {"CLAIMSFLOW_SYNTHETIC_ONLY": "true"},
        stdout,
        stderr,
    )

    result = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert result["status"] == "ok"
    assert result["synthetic_only"] is True
    assert result["file_count"] == 14
    assert Path(result["manifest"]) == output / "manifest.json"
    assert output.joinpath("manifest.json").is_file()


def test_generate_fails_closed_when_synthetic_boundary_is_disabled(tmp_path: Path) -> None:
    stdout = StringIO()
    stderr = StringIO()
    output = tmp_path / "prohibited"

    exit_code = main(
        [
            "generate",
            "--service-month",
            "2026-07",
            "--output",
            str(output),
        ],
        {"CLAIMSFLOW_SYNTHETIC_ONLY": "false"},
        stdout,
        stderr,
    )

    result = json.loads(stderr.getvalue())
    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert "real data is prohibited" in result["reason"]
    assert not output.exists()


def test_generate_reports_unsafe_service_month_without_traceback(tmp_path: Path) -> None:
    stdout = StringIO()
    stderr = StringIO()
    output = tmp_path / "unsafe-month"

    exit_code = main(
        [
            "generate",
            "--service-month",
            "9999-12",
            "--output",
            str(output),
        ],
        {"CLAIMSFLOW_SYNTHETIC_ONLY": "true"},
        stdout,
        stderr,
    )

    result = json.loads(stderr.getvalue())
    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert result["status"] == "error"
    assert "service month year" in result["reason"]
    assert not output.exists()


def test_ingest_prints_a_reconciled_control_plane_summary(tmp_path: Path) -> None:
    delivery = generate_delivery(
        GenerationConfig.from_values(seed=42, claim_count=4, service_month="2026-07"),
        tmp_path / "delivery",
    )
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        [
            "ingest",
            "--manifest",
            str(delivery.manifest_path),
            "--workspace",
            str(tmp_path / "workspace"),
            "--contracts",
            str(ROOT / "contracts/source-data"),
        ],
        {"CLAIMSFLOW_SYNTHETIC_ONLY": "true"},
        stdout,
        stderr,
    )

    result = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert result["status"] == "ok"
    assert result["decision"] == "processed"
    assert result["synthetic_only"] is True
    assert result["file_count"] == result["processed_files"] == 14
    assert result["raw_rows"] == result["declared_rows"] == result["accepted"]
    assert result["reconciled"] is True


def test_ingest_fails_closed_without_synthetic_runtime_boundary(tmp_path: Path) -> None:
    delivery = generate_delivery(
        GenerationConfig.from_values(seed=42, claim_count=2, service_month="2026-07"),
        tmp_path / "delivery",
    )
    stdout = StringIO()
    stderr = StringIO()
    workspace = tmp_path / "workspace"

    exit_code = main(
        [
            "ingest",
            "--manifest",
            str(delivery.manifest_path),
            "--workspace",
            str(workspace),
            "--contracts",
            str(ROOT / "contracts/source-data"),
        ],
        {"CLAIMSFLOW_SYNTHETIC_ONLY": "false"},
        stdout,
        stderr,
    )

    result = json.loads(stderr.getvalue())
    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert "real data is prohibited" in result["reason"]
    assert not workspace.exists()
