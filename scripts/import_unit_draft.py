"""차시 draft JSON → unit_setups.

사용:
  python -m scripts.import_unit_draft path/to/draft.json [--week-id u_xxx]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, init_db
from app.importers import upsert_unit_draft


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("json_path", type=Path)
    p.add_argument("--week-id", default=None)
    args = p.parse_args()
    draft = json.loads(args.json_path.read_text(encoding="utf-8"))
    init_db()
    db = SessionLocal()
    try:
        sid = upsert_unit_draft(db, draft, week_id=args.week_id)
        print("OK - unit_setup id =", sid)
    finally:
        db.close()


if __name__ == "__main__":
    main()
