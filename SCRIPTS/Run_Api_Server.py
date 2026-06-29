# -*- coding: utf-8 -*-

"""Run the local FastAPI backend for client development."""

from __future__ import annotations

from pathlib import Path
import sys

import uvicorn


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from APP.SHARED.settings import settings


def main() -> int:
    uvicorn.run(
        "APP.SERVER.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=False,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
