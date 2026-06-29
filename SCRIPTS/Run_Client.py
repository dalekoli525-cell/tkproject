# -*- coding: utf-8 -*-

"""Launch the production desktop client."""

from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from APP.CLIENT.Client_App import main


if __name__ == "__main__":
    raise SystemExit(main())
