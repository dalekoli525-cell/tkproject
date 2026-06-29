"""Environment-backed settings for server, worker, and local tools."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from APP.SHARED.constants import DEFAULT_PROXY_PORT_START
from APP.SHARED.constants import DEFAULT_RENDER_WAIT_SECONDS
from APP.SHARED.constants import MIN_RENDER_WAIT_SECONDS


ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT_DIR / ".env"
load_dotenv(ENV_FILE)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class AppSettings:
    app_name: str = os.getenv("APP_NAME", "TK AI CRM")
    environment: str = os.getenv("APP_ENV", "local")

    database_url: str = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://tk_user:tk_password@127.0.0.1:3306/tk_ai_crm",
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    ai_base_url: str = os.getenv("AI_BASE_URL", "http://127.0.0.1:11434")
    ai_model: str = os.getenv("AI_MODEL", "minimax-m3:cloud")
    client_api_base_url: str = os.getenv("CLIENT_API_BASE_URL", "http://127.0.0.1:8000")

    profile_root: Path = Path(
        os.getenv("BROWSER_PROFILE_ROOT", str(ROOT_DIR / "runtime" / "profiles"))
    )
    clash_config_dir: Path = Path(
        os.getenv(
            "CLASH_CONFIG_DIR",
            str(Path.home() / "AppData" / "Roaming" / "io.github.clash-verge-rev.clash-verge-rev"),
        )
    )
    clash_api_base_url: str = os.getenv("CLASH_API_BASE_URL", "http://127.0.0.1:9097")
    clash_api_secret: str = os.getenv("CLASH_API_SECRET", "set-your-secret")
    proxy_port_start: int = _int_env("PROXY_PORT_START", DEFAULT_PROXY_PORT_START)
    tiktok_render_wait_seconds: int = max(
        MIN_RENDER_WAIT_SECONDS,
        min(180, _int_env("TIKTOK_RENDER_WAIT_SECONDS", DEFAULT_RENDER_WAIT_SECONDS)),
    )

    server_host: str = os.getenv("SERVER_HOST", "0.0.0.0")
    server_port: int = _int_env("SERVER_PORT", 8000)
    worker_concurrency: int = max(1, min(20, _int_env("WORKER_CONCURRENCY", 2)))


settings = AppSettings()
