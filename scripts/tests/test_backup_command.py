"""The scheduled backup may target only this Compose project's database."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy/backup.sh"


class BackupCommandTests(unittest.TestCase):
    def test_uses_dedicated_container_and_full_backup(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            docker = directory / "docker"
            log = directory / "docker.log"
            docker.write_text(
                "#!/bin/sh\n"
                'printf \'%s\\n\' "$*" >> "$BACKUP_DOCKER_LOG"\n'
                "if [ \"$1\" = compose ]; then printf '%s\\n' whisky-db-123; fi\n"
            )
            docker.chmod(0o755)
            result = subprocess.run(
                [str(SCRIPT)],
                env={
                    **os.environ,
                    "PATH": f"{directory}:{os.environ['PATH']}",
                    "BACKUP_DOCKER_LOG": str(log),
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = log.read_text().splitlines()
            self.assertEqual(len(calls), 2)
            self.assertIn("-f", calls[0])
            self.assertIn("compose.research.yaml", calls[0])
            self.assertEqual(
                calls[1],
                "exec --user postgres whisky-db-123 pgbackrest "
                "--stanza=whisky --repo1-bundle backup --type=full",
            )


if __name__ == "__main__":
    unittest.main()
