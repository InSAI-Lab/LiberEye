from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    load_dotenv(ROOT / ".env", override=False)
    if not os.getenv("LIBEREYE_API_TOKEN") and os.getenv("LIBEREYE_ALLOW_INSECURE") != "1":
        raise SystemExit("Set LIBEREYE_API_TOKEN or run scripts/configure_cloud.py first")
    uvicorn.run(
        "libereye.cloud_api:app",
        host=os.getenv("LIBEREYE_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", os.getenv("LIBEREYE_PORT", "8080"))),
        workers=1, reload=False, access_log=False,
        log_level=os.getenv("LIBEREYE_LOG_LEVEL", "info").lower(),
        limit_concurrency=16, timeout_keep_alive=5,
    )


if __name__ == "__main__":
    main()
