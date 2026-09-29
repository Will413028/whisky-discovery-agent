"""Check the rendered T09 Compose graph before any private deployment."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def _requires(services: dict[str, Any], child: str, parent: str, label: str) -> None:
    condition = (
        services.get(child, {}).get("depends_on", {}).get(parent, {}).get("condition")
    )
    if condition != "service_completed_successfully":
        raise ValueError(f"{label} must wait for successful {parent}")


def _db_user(service: dict[str, Any]) -> str | None:
    url = service.get("environment", {}).get("WHISKY_DATABASE_URL", "")
    return urlsplit(url).username


def validate_base_graph(services: dict[str, Any]) -> None:
    api = services.get("api", {})
    if (
        _db_user(api) != "whisky_runtime"
        or api.get("environment", {}).get("WHISKY_RECOVERY_REQUIRED") != "1"
        or "/health/ready" not in " ".join(api.get("healthcheck", {}).get("test", []))
    ):
        raise ValueError("base API must use the gated runtime role and readiness")
    if _db_user(services.get("migrate", {})) != "whisky_ddl":
        raise ValueError("base migration must use the DDL role")
    db = services.get("db", {})
    if (
        not db.get("image", "").startswith("whisky-discovery-postgres:")
        or "archive_mode=on" not in db.get("command", [])
        or not any(
            secret.get("source") == "pgbackrest_config"
            for secret in db.get("secrets", [])
        )
    ):
        raise ValueError("base database must preserve WAL archiving")


def validate_graph(services: dict[str, Any]) -> None:
    validate_base_graph(services)
    _requires(services, "api", "control-reconcile", "api recovery gate")
    _requires(services, "worker", "control-reconcile", "worker recovery gate")
    _requires(services, "control-reconcile", "db-login-gate", "database login gate")
    _requires(services, "db-login-gate", "migrate", "login migration gate")
    _requires(services, "migrate", "db-roles", "product role gate")
    _requires(services, "temporal-schema", "db-roles", "Temporal role gate")
    _requires(services, "temporal", "temporal-schema", "Temporal schema gate")
    if (
        services.get("web", {}).get("depends_on", {}).get("api", {}).get("condition")
        != "service_healthy"
    ):
        raise ValueError("Web must wait for a healthy gated API")
    reconcile = services["control-reconcile"]["environment"]
    worker = services["worker"]["environment"]
    primary = reconcile.get("WHISKY_OCI_CONTROL_BUCKET")
    witness = reconcile.get("WHISKY_OCI_CONTROL_WITNESS_BUCKET")
    if (
        reconcile.get("WHISKY_RECOVERY_MODE") != "isolated"
        or not primary
        or not witness
        or primary == witness
        or worker.get("WHISKY_OCI_CONTROL_WITNESS_BUCKET") != witness
    ):
        raise ValueError("Independent control inventories are required")
    if (
        services["api"]["environment"].get("WHISKY_RECOVERY_REQUIRED") != "1"
        or worker.get("WHISKY_RECOVERY_REQUIRED") != "1"
        or "/health/ready" not in " ".join(services["api"]["healthcheck"]["test"])
    ):
        raise ValueError("Serving processes require a live recovery gate")
    if (
        services["api"]["environment"].get("WHISKY_DATABASE_URL")
        != worker.get("WHISKY_DATABASE_URL")
        or _db_user(services["worker"]) != "whisky_runtime"
        or services["control-reconcile"]["environment"].get("WHISKY_DATABASE_URL")
        != services["migrate"]["environment"].get("WHISKY_DATABASE_URL")
        or services["temporal"]["environment"].get("POSTGRES_USER")
        != "whisky_temporal_runtime"
        or services["temporal-schema"]["environment"].get("SQL_USER")
        != "whisky_temporal_schema"
    ):
        raise ValueError("Runtime and schema database roles must remain separate")


def main() -> None:
    values = {
        **os.environ,
        "WHISKY_PG_RELEASE": "check",
        "WHISKY_PRODUCT_DB_PASSWORD": "check",
        "WHISKY_PRODUCT_DDL_PASSWORD": "check",
        "WHISKY_TEMPORAL_DB_PASSWORD": "check",
        "WHISKY_TEMPORAL_SCHEMA_PASSWORD": "check",
        "WHISKY_RUNTIME_DATABASE_URL": (
            "postgresql+psycopg://whisky_runtime:check@db:5432/whisky"
        ),
        "WHISKY_MIGRATION_DATABASE_URL": (
            "postgresql+psycopg://whisky_ddl:check@db:5432/whisky"
        ),
        "WHISKY_TEMPORAL_NAMESPACE": "whisky",
        "WHISKY_TEMPORAL_TASK_QUEUE": "whisky-research",
        "WHISKY_CLOUDFLARE_ACCOUNT_ID": "check",
        "WHISKY_OCI_NAMESPACE": "check",
        "WHISKY_OCI_CONTROL_BUCKET": "whisky-discovery-controls",
        "WHISKY_OCI_CONTROL_WITNESS_BUCKET": "whisky-discovery-control-witness",
    }
    command = [
        "docker",
        "compose",
        "--env-file",
        str(ROOT / "deploy/.env.example"),
        "-f",
        str(ROOT / "deploy/compose.yaml"),
        "config",
        "--format",
        "json",
    ]
    base = subprocess.run(
        command,
        env=values,
        capture_output=True,
        text=True,
        check=True,
    )
    validate_base_graph(json.loads(base.stdout)["services"])
    command = [
        *command[:6],
        "-f",
        str(ROOT / "deploy/compose.research.yaml"),
        *command[6:],
    ]
    result = subprocess.run(
        command,
        env=values,
        capture_output=True,
        text=True,
        check=True,
    )
    validate_graph(json.loads(result.stdout)["services"])
    print("T09 private startup graph PASS")


if __name__ == "__main__":
    main()
