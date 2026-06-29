"""Offline validation for the rewritten project.

This script avoids MySQL, Redis, AI services, and real browsers. It validates
the local schemas and Clash multi-port config generation only.
"""

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from APP.SHARED.schemas import BrowserEnvironment
from APP.WORKER.clash_config import ClashMultiProxyConfigBuilder


def main() -> int:
    environments = [
        BrowserEnvironment(
            code="001",
            name="TikTok-MY-001",
            proxy_node="Residential-1",
            local_proxy_port=7901,
            profile_dir=Path("runtime/profiles/env_001"),
        ),
        BrowserEnvironment(
            code="002",
            name="TikTok-MY-002",
            proxy_node="Residential-2",
            local_proxy_port=7902,
            profile_dir=Path("runtime/profiles/env_002"),
        ),
    ]

    rendered = ClashMultiProxyConfigBuilder.render(environments)

    assert "IN-PORT,7901,ENV_001_PROXY" in rendered.rules_yaml
    assert "IN-PORT,7902,ENV_002_PROXY" in rendered.rules_yaml
    assert "Residential-1" in rendered.groups_yaml
    assert "Residential-2" in rendered.groups_yaml
    assert "listeners:" in rendered.full_yaml

    print("offline validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
