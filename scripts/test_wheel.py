"""Build and test the installed wheel in a clean environment outside the checkout."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"


def main() -> None:
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    with tempfile.TemporaryDirectory(prefix="whisky-wheel-") as directory:
        root = Path(directory)

        def run(*args: str) -> None:
            subprocess.run(args, cwd=root, env=env, check=True)

        run("uv", "build", "--project", str(BACKEND), "--wheel", "--out-dir", str(root))
        run(
            "uv",
            "export",
            "--project",
            str(BACKEND),
            "--frozen",
            "--no-emit-project",
            "--output-file",
            str(root / "requirements.txt"),
            "--quiet",
        )
        run("uv", "venv", "--python", "3.13", str(root / "venv"))
        python = str(root / "venv/bin/python")
        run(
            "uv",
            "pip",
            "install",
            "--python",
            python,
            "-r",
            str(root / "requirements.txt"),
            str(next(root.glob("*.whl"))),
        )
        run(
            python,
            "-I",
            "-c",
            "from pathlib import Path; from alembic.script import ScriptDirectory; "
            "import whisky.bootstrap.migrate as migration; "
            "scripts = Path(migration.__file__).parents[1] / 'migrations'; "
            "assert (scripts / 'env.py').is_file(); "
            "assert ScriptDirectory(str(scripts)).get_current_head() "
            "== '0012_recovery_gate'",
        )
        shutil.copy(BACKEND / "tests/test_installed.py", root / "test_installed.py")
        shutil.copy(
            BACKEND / "tests/integration/test_temporal.py", root / "test_temporal.py"
        )
        (root / "pytest.ini").write_text(
            "[pytest]\nasyncio_mode = auto\nmarkers =\n    integration: real service\n"
        )
        run(python, "-I", "-m", "pytest", "-q", str(root))


if __name__ == "__main__":
    main()
