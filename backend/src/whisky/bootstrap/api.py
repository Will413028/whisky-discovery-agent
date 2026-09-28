"""HTTP process entry point."""

import argparse

import uvicorn
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Whisky Discovery Agent")

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        """Process liveness only; does not claim DB or worker readiness."""
        return {"status": "ok"}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8417)
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port)
