"""Typed runtime configuration with a fail-closed synthetic-data boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

SUPPORTED_ENVIRONMENTS = frozenset({"local", "dev-demo"})
DEFAULT_MAXIMUM_BYTES_BILLED = 1_073_741_824
MAXIMUM_BYTES_BILLED_BY_ENVIRONMENT = {
    "local": 1_073_741_824,
    "dev-demo": 10_737_418_240,
}


class ConfigurationError(ValueError):
    """Raised when runtime configuration violates an approved boundary."""


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Non-secret settings shared by local commands and future adapters."""

    environment: str
    synthetic_only: bool
    log_level: str
    gcp_project: str | None
    bigquery_location: str
    maximum_bytes_billed: int

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> RuntimeSettings:
        """Build validated settings from an environment-like mapping."""

        environment = values.get("CLAIMSFLOW_ENVIRONMENT", "local").strip().lower()
        if environment not in SUPPORTED_ENVIRONMENTS:
            supported = ", ".join(sorted(SUPPORTED_ENVIRONMENTS))
            raise ConfigurationError(f"CLAIMSFLOW_ENVIRONMENT must be one of: {supported}")

        synthetic_flag = values.get("CLAIMSFLOW_SYNTHETIC_ONLY", "true").strip().lower()
        if synthetic_flag != "true":
            raise ConfigurationError(
                "CLAIMSFLOW_SYNTHETIC_ONLY must remain true; real data is prohibited"
            )

        gcp_project = values.get("CLAIMSFLOW_GCP_PROJECT", "").strip() or None
        if environment == "dev-demo" and gcp_project is None:
            raise ConfigurationError(
                "CLAIMSFLOW_GCP_PROJECT is required for the dev-demo environment"
            )

        raw_limit = values.get("CLAIMSFLOW_MAXIMUM_BYTES_BILLED", str(DEFAULT_MAXIMUM_BYTES_BILLED))
        try:
            maximum_bytes_billed = int(raw_limit)
        except ValueError as error:
            raise ConfigurationError(
                "CLAIMSFLOW_MAXIMUM_BYTES_BILLED must be an integer"
            ) from error
        if maximum_bytes_billed <= 0:
            raise ConfigurationError("CLAIMSFLOW_MAXIMUM_BYTES_BILLED must be greater than zero")
        environment_limit = MAXIMUM_BYTES_BILLED_BY_ENVIRONMENT[environment]
        if maximum_bytes_billed > environment_limit:
            raise ConfigurationError(
                "CLAIMSFLOW_MAXIMUM_BYTES_BILLED exceeds the "
                f"{environment} limit of {environment_limit}"
            )

        log_level = values.get("CLAIMSFLOW_LOG_LEVEL", "INFO").strip().upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("CLAIMSFLOW_LOG_LEVEL is unsupported")

        location = values.get("CLAIMSFLOW_BIGQUERY_LOCATION", "US").strip().upper()
        if not location:
            raise ConfigurationError("CLAIMSFLOW_BIGQUERY_LOCATION cannot be blank")

        return cls(
            environment=environment,
            synthetic_only=True,
            log_level=log_level,
            gcp_project=gcp_project,
            bigquery_location=location,
            maximum_bytes_billed=maximum_bytes_billed,
        )

    def public_summary(self) -> dict[str, object]:
        """Return diagnostic values that are safe to display in logs and CI."""

        return {
            "environment": self.environment,
            "synthetic_only": self.synthetic_only,
            "log_level": self.log_level,
            "cloud_configured": self.gcp_project is not None,
            "bigquery_location": self.bigquery_location,
            "maximum_bytes_billed": self.maximum_bytes_billed,
        }
