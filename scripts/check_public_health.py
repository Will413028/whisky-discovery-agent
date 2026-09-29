"""Anonymous external availability probe; never accepts credentials or a URL."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

PUBLIC_READY_URL = "https://whisky-discovery-web.fathompod.workers.dev/health/ready"


class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


open_readiness = build_opener(RejectRedirect()).open


def check_public_health() -> None:
    try:
        request = Request(
            PUBLIC_READY_URL,
            headers={
                "Cache-Control": "no-cache",
                "User-Agent": "WhiskyDiscoveryAvailability/1.0",
            },
        )
        with open_readiness(request, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError("Public readiness did not return HTTP 200")
            if response.headers.get("Cache-Control") != "no-store":
                raise RuntimeError("Public readiness was not explicitly uncached")
            body = response.read(1025)
            if len(body) > 1024 or json.loads(body) != {"status": "ok"}:
                raise RuntimeError("Public readiness returned an unexpected body")
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        if isinstance(exc, HTTPError):
            exc.close()
        raise RuntimeError("Public readiness is unavailable") from exc


if __name__ == "__main__":
    check_public_health()
    print("Public Worker/VPC/Web/API/database readiness is healthy")
