import tempfile
import unittest
from pathlib import Path

from check_python_boundaries import violations


class PythonBoundariesTest(unittest.TestCase):
    def check_source(self, path: str, source: str) -> list[str]:
        with tempfile.TemporaryDirectory(prefix="whisky-boundary-") as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            return violations(root)

    def test_domain_rejects_framework_import(self):
        for framework in ("sqlalchemy", "fastapi", "temporalio", "pydantic_ai"):
            with self.subTest(framework=framework):
                errors = self.check_source(
                    "whisky/modules/research/domain/task.py", f"import {framework}\n"
                )
                self.assertTrue(errors, f"domain must reject {framework}")

    def test_cross_module_internals_rejected(self):
        for source in (
            "from whisky.modules.catalog.adapters import repository",
            "from ...catalog.adapters import repository",
            "from whisky.modules.catalog import adapters",
            "import whisky.modules.catalog.domain.item",
        ):
            with self.subTest(source=source):
                self.assertTrue(
                    self.check_source(
                        "whisky/modules/research/application/start.py", source
                    )
                )

    def test_public_and_same_module_imports_allowed(self):
        self.assertEqual(
            [],
            self.check_source(
                "whisky/modules/research/application/start.py",
                "from whisky.modules.catalog.public import find_item\n"
                "from ..domain import task\nfrom datetime import datetime\n",
            ),
        )

    def test_domain_cannot_reach_infrastructure_through_local_layers(self):
        for source in (
            "from ..adapters import repository",
            "from whisky.platform import database",
            "from whisky.bootstrap import api",
        ):
            with self.subTest(source=source):
                self.assertTrue(
                    self.check_source("whisky/modules/research/domain/task.py", source)
                )

    def test_single_file_domain_obeys_same_boundaries(self):
        for source in ("import sqlalchemy", "from whisky.platform import database"):
            with self.subTest(source=source):
                self.assertTrue(
                    self.check_source("whisky/modules/research/domain.py", source)
                )


if __name__ == "__main__":
    unittest.main()
