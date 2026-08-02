"""DB 파일·테이블 생성.

사용:
  cd server
  python -m scripts.init_db
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import DEFAULT_DB, settings
from app.db import init_db


def main() -> None:
    init_db()
    print("OK - tables created")
    print("DATABASE_URL =", settings.database_url)
    print("DB file     =", DEFAULT_DB if "sqlite" in settings.database_url else "(non-sqlite)")


if __name__ == "__main__":
    main()
