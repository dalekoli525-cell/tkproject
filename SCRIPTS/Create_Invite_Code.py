# -*- coding: utf-8 -*-

"""Create or update a six-digit invite code for local/admin setup."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from APP.SERVER.security import create_invite_code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True, help="6 位数字邀请码")
    parser.add_argument("--role", default="operator", choices=["admin", "operator"])
    parser.add_argument("--uses", default=1, type=int)
    parser.add_argument("--inactive", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    invite = create_invite_code(
        code=args.code,
        role=args.role,
        uses_remaining=args.uses,
        is_active=not args.inactive,
    )
    print(
        "邀请码已保存："
        f"code={invite['code']} role={invite['role']} "
        f"剩余次数={invite['uses_remaining']} 启用={invite['is_active']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
