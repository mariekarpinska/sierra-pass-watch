"""One tiny HTTP helper for every outbound fetch in the pipeline.

Security posture in one place (see SECURITY.md): every source URL is a
constant in its client module — nothing user-supplied ever becomes a URL, so
there is no SSRF surface. Every request carries an explicit timeout (a hung
public API must never hang a poll cycle) and an honest User-Agent (NWS
requires one; the others appreciate it).
"""
from __future__ import annotations

import requests

USER_AGENT = "sierra-safe (https://github.com/mariekarpinska/sierra-safe)"

DEFAULT_TIMEOUT_S = 15


def get_json(url: str, params: dict | None = None, timeout: float = DEFAULT_TIMEOUT_S) -> dict:
    """GET a JSON document. Raises requests.HTTPError on non-2xx."""
    response = requests.get(
        url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT}
    )
    response.raise_for_status()
    return response.json()
