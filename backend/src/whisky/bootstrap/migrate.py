"""Explicit product schema migration; never runs from API startup."""

import argparse
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine


def upgrade(engine: Engine, scripts: Path | None = None) -> None:
    config = Config()
    config.set_main_option(
        "script_location", str(scripts or Path(__file__).parents[1] / "migrations")
    )
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scripts",
        type=Path,
        help="Source checkout Alembic directory; installed wheels include it",
    )
    args = parser.parse_args()
    engine = create_engine(os.environ["WHISKY_DATABASE_URL"], pool_pre_ping=True)
    try:
        upgrade(engine, args.scripts)
    finally:
        engine.dispose()
