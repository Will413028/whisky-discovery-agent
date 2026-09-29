"""Private serving must depend on a successful external-log reconciliation."""

import unittest

from scripts.check_deploy_gate import validate_base_graph, validate_graph


class DeployGateTests(unittest.TestCase):
    def test_base_compose_cannot_serve_with_admin_url_or_liveness_gate(self) -> None:
        services = {
            "api": {
                "environment": {
                    "WHISKY_DATABASE_URL": "postgresql://whisky:old@db/whisky"
                },
                "healthcheck": {"test": ["/health/live"]},
            },
            "migrate": {
                "environment": {
                    "WHISKY_DATABASE_URL": "postgresql://whisky:old@db/whisky"
                }
            },
            "db": {"image": "postgres:18"},
        }
        with self.assertRaisesRegex(
            ValueError, "base API must use the gated runtime role"
        ):
            validate_base_graph(services)

    def test_api_without_recovery_dependency_is_rejected(self) -> None:
        services = {
            "api": {
                "environment": {
                    "WHISKY_DATABASE_URL": "postgresql://whisky_runtime:check@db/whisky",
                    "WHISKY_RECOVERY_REQUIRED": "1",
                },
                "healthcheck": {"test": ["/health/ready"]},
                "depends_on": {
                    "migrate": {"condition": "service_completed_successfully"}
                },
            },
            "migrate": {
                "environment": {
                    "WHISKY_DATABASE_URL": "postgresql://whisky_ddl:check@db/whisky"
                }
            },
            "db": {
                "image": "whisky-discovery-postgres:check",
                "command": ["postgres", "archive_mode=on"],
                "secrets": [{"source": "pgbackrest_config"}],
            },
            "worker": {
                "depends_on": {
                    "control-reconcile": {"condition": "service_completed_successfully"}
                }
            },
            "control-reconcile": {
                "depends_on": {
                    "migrate": {"condition": "service_completed_successfully"}
                },
                "environment": {
                    "WHISKY_RECOVERY_MODE": "isolated",
                    "WHISKY_OCI_CONTROL_WITNESS_BUCKET": "witness",
                },
            },
        }
        with self.assertRaisesRegex(ValueError, "api recovery gate"):
            validate_graph(services)


if __name__ == "__main__":
    unittest.main()
