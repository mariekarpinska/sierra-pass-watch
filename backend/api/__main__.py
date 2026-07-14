"""Dev server entry point: `python -m api`. Equivalent to
`uvicorn api.main:app --port 5080 --no-server-header`; the module form exists
so the README's run command works from any shell without remembering flags."""
from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("api.main:app", host="127.0.0.1", port=5080, server_header=False)


if __name__ == "__main__":
    main()
