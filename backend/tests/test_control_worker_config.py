"""The production queue cannot enable half of an OCI control journal."""

import pytest

from whisky.bootstrap.worker import (
    cloudflare_token_from_values,
    control_journal_from_values,
)
from whisky.modules.control.journal import MemoryControlJournal


def test_control_journal_is_opt_in_and_partial_configuration_fails(monkeypatch):
    assert control_journal_from_values({}) is None
    with pytest.raises(ValueError, match="control journal"):
        control_journal_from_values({"WHISKY_OCI_CONTROL_BUCKET": "whisky"})
    with pytest.raises(ValueError, match="control journal"):
        control_journal_from_values(
            {
                "WHISKY_OCI_CONTROL_BUCKET": "whisky",
                "WHISKY_OCI_NAMESPACE": "namespace",
                "WHISKY_OCI_CONTROL_CONFIG_FILE": "relative/key.conf",
            }
        )
    with pytest.raises(ValueError, match="control journal"):
        control_journal_from_values(
            {
                "WHISKY_OCI_CONTROL_BUCKET": "whisky",
                "WHISKY_OCI_NAMESPACE": "namespace",
                "WHISKY_OCI_CONTROL_CONFIG_FILE": "/run/secrets/oci-runtime.conf",
            }
        )

    journal = MemoryControlJournal()
    called = []

    def factory(config_file, namespace, bucket):
        called.append((config_file, namespace, bucket))
        return journal

    monkeypatch.setattr(
        "whisky.bootstrap.worker.OciControlJournal.from_config_file", factory
    )
    paired = control_journal_from_values(
        {
            "WHISKY_OCI_CONTROL_BUCKET": "whisky",
            "WHISKY_OCI_CONTROL_WITNESS_BUCKET": "whisky-witness",
            "WHISKY_OCI_NAMESPACE": "namespace",
            "WHISKY_OCI_CONTROL_CONFIG_FILE": "/run/secrets/oci-runtime.conf",
        }
    )
    assert paired is not None
    assert called == [
        ("/run/secrets/oci-runtime.conf", "namespace", "whisky"),
        ("/run/secrets/oci-runtime.conf", "namespace", "whisky-witness"),
    ]


def test_worker_reads_model_token_from_dedicated_secret_file(tmp_path):
    token_file = tmp_path / "workers-ai-token"
    token_file.write_text("project-token\n")
    assert (
        cloudflare_token_from_values(
            {"WHISKY_CLOUDFLARE_AI_TOKEN_FILE": str(token_file)}
        )
        == "project-token"
    )
    with pytest.raises(ValueError, match="token source"):
        cloudflare_token_from_values(
            {
                "WHISKY_CLOUDFLARE_AI_TOKEN": "inline",
                "WHISKY_CLOUDFLARE_AI_TOKEN_FILE": str(token_file),
            }
        )
    with pytest.raises(ValueError, match="absolute"):
        cloudflare_token_from_values(
            {"WHISKY_CLOUDFLARE_AI_TOKEN_FILE": "relative/path"}
        )
