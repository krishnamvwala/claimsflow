from __future__ import annotations

import pytest

from claimsflow.config import ConfigurationError, RuntimeSettings


def test_local_defaults_are_synthetic_and_bounded() -> None:
    settings = RuntimeSettings.from_mapping({})

    assert settings.environment == "local"
    assert settings.synthetic_only is True
    assert settings.maximum_bytes_billed == 1_073_741_824
    assert settings.gcp_project is None


def test_real_data_boundary_fails_closed() -> None:
    with pytest.raises(ConfigurationError, match="real data is prohibited"):
        RuntimeSettings.from_mapping({"CLAIMSFLOW_SYNTHETIC_ONLY": "false"})


def test_dev_demo_requires_a_project() -> None:
    with pytest.raises(ConfigurationError, match="required for the dev-demo"):
        RuntimeSettings.from_mapping({"CLAIMSFLOW_ENVIRONMENT": "dev-demo"})


def test_dev_demo_accepts_non_secret_project_configuration() -> None:
    settings = RuntimeSettings.from_mapping(
        {
            "CLAIMSFLOW_ENVIRONMENT": "dev-demo",
            "CLAIMSFLOW_GCP_PROJECT": "claimsflow-demo-synthetic",
        }
    )

    assert settings.gcp_project == "claimsflow-demo-synthetic"
    assert settings.public_summary()["cloud_configured"] is True


@pytest.mark.parametrize("value", ["0", "-1", "not-a-number"])
def test_query_limit_must_be_a_positive_integer(value: str) -> None:
    with pytest.raises(ConfigurationError, match="MAXIMUM_BYTES_BILLED"):
        RuntimeSettings.from_mapping({"CLAIMSFLOW_MAXIMUM_BYTES_BILLED": value})


@pytest.mark.parametrize(
    ("environment", "value"),
    [
        ("local", "1073741825"),
        ("dev-demo", "10737418241"),
    ],
)
def test_query_limit_must_not_exceed_environment_cap(
    environment: str,
    value: str,
) -> None:
    values = {
        "CLAIMSFLOW_ENVIRONMENT": environment,
        "CLAIMSFLOW_MAXIMUM_BYTES_BILLED": value,
    }
    if environment == "dev-demo":
        values["CLAIMSFLOW_GCP_PROJECT"] = "claimsflow-demo-synthetic"

    with pytest.raises(ConfigurationError, match="exceeds"):
        RuntimeSettings.from_mapping(values)
