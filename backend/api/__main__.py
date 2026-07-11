"""Dev server entry point: `python -m api`.

On Windows, psycopg's async mode needs a selector event loop, so it is set here
before uvicorn starts. On Linux and macOS, `uvicorn api.main:app` works directly.
"""
from __future__ import annotations

import asyncio
import sys

import uvicorn

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def main() -> None:
    config = uvicorn.Config("api.main:app", host="127.0.0.1", port=5080, server_header=False)
    # Server.serve() inside asyncio.run() uses the policy set above, unlike
    # `python -m uvicorn`, which builds its own (proactor) loop first.
    asyncio.run(uvicorn.Server(config).serve())


if __name__ == "__main__":
    main()
