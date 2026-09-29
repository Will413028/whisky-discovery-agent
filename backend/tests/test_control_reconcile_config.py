"""A restored private service requires both independent control inventories."""

import pytest

from whisky.bootstrap.control_reconcile import run


def test_recovery_refuses_a_single_control_bucket():
    with pytest.raises(ValueError, match="witness"):
        run(
            {
                "WHISKY_RECOVERY_MODE": "isolated",
                "WHISKY_DATABASE_URL": "postgresql+psycopg://test:pass@db/whisky",
                "WHISKY_OCI_CONTROL_CONFIG_FILE": "/run/secrets/control.conf",
                "WHISKY_OCI_NAMESPACE": "namespace",
                "WHISKY_OCI_CONTROL_BUCKET": "control",
            }
        )
