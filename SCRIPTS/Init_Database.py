"""Create the rewritten database tables.

Run this only when DATABASE_URL points to the intended server database.
"""

from APP.SERVER.database import Base
from APP.SERVER.database import engine

# Register models with metadata.
from APP.SERVER import models  # noqa: F401


def main() -> int:
    Base.metadata.create_all(bind=engine)
    print("database initialized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
