"""Offline validation for the rewritten project.

This script avoids MySQL, Redis, AI services, and real browsers. It validates
the local schemas and Playwright direct proxy parsing only.
"""

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from APP.SHARED.schemas import BrowserEnvironment
from SCRIPTS.Open_Environment import choose_proxy_launch_config


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

    assert environments[0].proxy_node == "Residential-1"
    assert environments[1].local_proxy_port == 7902

    direct, direct_note = choose_proxy_launch_config(7901, "DIRECT")
    assert direct.server is None
    assert "不会强制使用" in direct_note

    host_port_auth, note = choose_proxy_launch_config(
        7901,
        "45.123.102.122:44001:u6X69f88592aac67:9ZuAnOpdSyqUKi4hjD"
    )
    assert host_port_auth.server == "http://45.123.102.122:44001"
    assert host_port_auth.username == "u6X69f88592aac67"
    assert host_port_auth.password == "9ZuAnOpdSyqUKi4hjD"
    assert "直连" in note

    url_auth, _ = choose_proxy_launch_config(
        7902,
        "http://gfO69ec353ab2a94:A5rZlUIPgFjtoYkJhQ@45.123.102.65:44001"
    )
    assert url_auth.server == "http://45.123.102.65:44001"
    assert url_auth.username == "gfO69ec353ab2a94"
    assert url_auth.password == "A5rZlUIPgFjtoYkJhQ"

    inline_url, _ = choose_proxy_launch_config(
        7903,
        "http://45.123.102.126:44001:gKi694bbe5262a03:IbSe20xY6q54TG8tHy"
    )
    assert inline_url.server == "http://45.123.102.126:44001"
    assert inline_url.username == "gKi694bbe5262a03"
    assert inline_url.password == "IbSe20xY6q54TG8tHy"

    invalid, invalid_note = choose_proxy_launch_config(7904, "not-a-valid-proxy")
    assert invalid.server is None
    assert "格式无法识别" in invalid_note

    print("offline validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
