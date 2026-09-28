"""Check direct Python imports against the module architecture."""

import argparse
import ast
from importlib.util import resolve_name
from pathlib import Path

FRAMEWORKS = {
    "sqlalchemy",
    "fastapi",
    "temporalio",
    "pydantic_ai",
    "psycopg",
    "alembic",
}


def violations(root: Path) -> list[str]:
    errors = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        parts = relative.with_suffix("").parts
        package = ".".join(parts[:-1])
        owner = parts[2] if parts[:2] == ("whisky", "modules") else None
        is_domain = owner is not None and parts[3:4] == ("domain",)
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    base = resolve_name("." * node.level + base, package)
                imports = [f"{base}.{alias.name}" for alias in node.names]
            else:
                continue
            for target in imports:
                if is_domain and target.split(".")[0] in FRAMEWORKS:
                    errors.append(f"{relative}:{node.lineno}: domain imports {target}")
                imported = target.split(".")
                if is_domain and imported[0] == "whisky":
                    own_domain = ["whisky", "modules", owner, "domain"]
                    if imported[:4] != own_domain:
                        errors.append(
                            f"{relative}:{node.lineno}: domain imports outer layer {target}"
                        )
                if (
                    owner
                    and imported[:2] == ["whisky", "modules"]
                    and len(imported) > 2
                    and imported[2] != owner
                    and imported[3:4] != ["public"]
                ):
                    errors.append(
                        f"{relative}:{node.lineno}: cross-module internal {target}"
                    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    root = parser.parse_args().root
    if not root.is_dir() or not any(root.rglob("*.py")):
        parser.error("source root must contain Python files")
    errors = violations(root)
    for error in errors:
        print(error)
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
