"""case_*_decisions*.json → Case + Run + Decision.

사용:
  python -m scripts.import_case_decisions ../files/case_001_decisions_v2.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, init_db
from app.importers import import_case_decisions_file
from app.models import Decision, Scene
from sqlalchemy import func, select


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("json_path", type=Path)
    p.add_argument("--no-benchmark", action="store_true")
    args = p.parse_args()
    init_db()
    db = SessionLocal()
    try:
        case_id, run_id = import_case_decisions_file(
            db, args.json_path, is_benchmark=not args.no_benchmark
        )
        n_dec = db.scalar(select(func.count()).select_from(Decision).where(Decision.run_id == run_id))
        print("OK - case_id =", case_id)
        print("     run_id  =", run_id)
        print("     decisions =", n_dec)
    finally:
        db.close()


if __name__ == "__main__":
    main()
