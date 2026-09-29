"""One-shot isolated PITR control-log reconciliation before private serving."""

import os
from collections.abc import Mapping

from sqlalchemy import create_engine

from whisky.modules.control.journal_oci import OciControlJournal
from whisky.modules.control.recovery import (
    reconcile_control_log,
    repair_witness_only,
)
from whisky.modules.control.store import ControlStore
from whisky.platform.recovery_gate import database_epoch, stamp_recovery_gate


def run(values: Mapping[str, str]) -> int:
    if values.get("WHISKY_RECOVERY_MODE") != "isolated":
        raise ValueError("Control recovery requires isolated mode")
    database_url = values.get("WHISKY_DATABASE_URL", "")
    config_file = values.get("WHISKY_OCI_CONTROL_CONFIG_FILE", "")
    namespace = values.get("WHISKY_OCI_NAMESPACE", "")
    bucket = values.get("WHISKY_OCI_CONTROL_BUCKET", "")
    witness_bucket = values.get("WHISKY_OCI_CONTROL_WITNESS_BUCKET", "")
    if not witness_bucket or witness_bucket == bucket:
        raise ValueError("Independent control witness bucket is required")
    if (
        not database_url.startswith("postgresql+psycopg://")
        or not config_file.startswith("/")
        or not namespace
        or not bucket
    ):
        raise ValueError("Dedicated DB and OCI recovery settings are required")
    journal = OciControlJournal.from_config_file(config_file, namespace, bucket)
    witness = OciControlJournal.from_config_file(config_file, namespace, witness_bucket)
    repaired = repair_witness_only(journal, witness)
    if repaired:
        print(f"Repaired {repaired} witness-only control objects")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        epoch = database_epoch(engine)
        count = len(reconcile_control_log(journal, ControlStore(engine), witness))
        stamp_recovery_gate(engine, epoch)
        return count
    finally:
        engine.dispose()


def main() -> None:
    count = run(os.environ)
    print(f"Reconciled {count} external control commands")
