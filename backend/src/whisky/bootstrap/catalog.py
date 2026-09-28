"""Publish a manually reviewed real catalog manifest to the configured product DB."""

import argparse
import os
from pathlib import Path

from sqlalchemy import create_engine

from whisky.modules.catalog.publication import load_reviewed_release
from whisky.modules.catalog.store import CatalogStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    release = load_reviewed_release(args.manifest.read_text())
    engine = create_engine(os.environ["WHISKY_DATABASE_URL"], pool_pre_ping=True)
    try:
        CatalogStore(engine).publish(release)
    finally:
        engine.dispose()
    print(f"Published catalog release {release.id}")
