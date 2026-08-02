"""tagger_web 내보내기 .jsonl → Case/Run/Decision/Scene.

사용:
  python -m scripts.import_jsonl path/to/export.jsonl
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, init_db
from app.importers import import_jsonl_export


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("jsonl_path", type=Path)
    args = p.parse_args()
    text = args.jsonl_path.read_text(encoding="utf-8")
    init_db()
    db = SessionLocal()
    try:
        case_id, run_id = import_jsonl_export(db, text)
        print("OK - case_id =", case_id)
        print("     run_id  =", run_id)
    finally:
        db.close()


if __name__ == "__main__":
    main()
