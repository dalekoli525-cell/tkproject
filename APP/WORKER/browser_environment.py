"""Playwright browser environment manager."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from APP.SHARED.constants import MIN_RENDER_WAIT_SECONDS
from APP.SHARED.schemas import BrowserEnvironment


class PlaywrightEnvironmentManager:
    """Launch one persistent Chromium profile through its assigned proxy port."""

    def __init__(
        self,
        environment: BrowserEnvironment,
        headless: bool = False,
        render_wait_seconds: int = 30,
    ):
        self.environment = environment
        self.headless = headless
        self.render_wait_seconds = max(MIN_RENDER_WAIT_SECONDS, render_wait_seconds)

    @contextmanager
    def context(self) -> Iterator[object]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run: python -m playwright install chromium"
            ) from exc

        Path(self.environment.profile_dir).mkdir(parents=True, exist_ok=True)
        playwright = sync_playwright().start()
        context = None

        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.environment.profile_dir),
                headless=self.headless,
                proxy={
                    "server": f"http://127.0.0.1:{self.environment.local_proxy_port}",
                },
                viewport={
                    "width": 1440,
                    "height": 960,
                },
                locale="ms-MY",
                timezone_id="Asia/Kuala_Lumpur",
            )
            yield context

        finally:
            if context is not None:
                context.close()
            playwright.stop()
