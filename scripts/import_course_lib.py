"""lf_course_lib_v1 JSON 파일을 DB로 적재.

브라우저에서 내보내려면 콘솔에서:
  copy(localStorage.getItem('lf_course_lib_v1'))
후 파일로 저장.

사용:
  python -m scripts.import_course_lib path/to/course_lib.json
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
from app.importers import upsert_course_lib


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("json_path", type=Path, help="lf_course_lib_v1 dump JSON")
    args = p.parse_args()
    raw = json.loads(args.json_path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        raw = {"v": 1, "courses": raw}
    init_db()
    db = SessionLocal()
    try:
        ids = upsert_course_lib(db, raw)
        print(f"OK - courses upserted: {len(ids)}")
        for i in ids:
            print(" ", i)
    finally:
        db.close()


if __name__ == "__main__":
    main()
