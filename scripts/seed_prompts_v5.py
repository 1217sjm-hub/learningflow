# -*- coding: utf-8 -*-
"""Seed DB: common prompt v5.4 + 스마트팜 과정별 프롬프트(있으면)."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.importers import upsert_prompt_version
from app.models import Course, CourseSetup, PromptVersion

HTML = ROOT.parent / "files" / "tagger_web.html"
MD = Path(r"c:\Users\kikiy\Downloads\20260728_스마트팜_시스템_모델링_및_분석_1주차_1차시_분할프롬프트_v5.1.md")


def extract_common_rules() -> str:
    html = HTML.read_text(encoding="utf-8")
    m = re.search(
        r"const DEFAULT_COMMON_RULES = `([\s\S]*?)`;\n\nconst DEFAULT_COURSE_TEMPLATE",
        html,
    )
    if not m:
        raise SystemExit("DEFAULT_COMMON_RULES not found in tagger_web.html")
    return m.group(1)


def extract_course_from_md() -> str | None:
    if not MD.is_file():
        return None
    md = MD.read_text(encoding="utf-8")
    idx = md.find("## 과정별 프롬프트")
    if idx < 0:
        return None
    body = md[idx + len("## 과정별 프롬프트") :].strip()
    tool = body.find("【이 도구 전용】")
    if tool >= 0:
        body = body[:tool].rstrip()
    return body


def main() -> None:
    init_db()
    common = extract_common_rules()
    course_body = extract_course_from_md()
    print("common len", len(common))
    if course_body:
        print("course len", len(course_body))
    else:
        print("course md missing - common only")

    db = SessionLocal()
    try:
        upsert_prompt_version(
            db,
            version="v5.4",
            body=common,
            notes="문단 허용·논리 연결·item 이어분할(·상/·하)·유형별 표현·◆승격 금지 · 개요 계층",
            make_default=True,
        )
        db.commit()
        row = db.scalar(select(PromptVersion).where(PromptVersion.is_default.is_(True)))
        assert row is not None
        print("default prompt:", row.version, "len=", len(row.body or ""))

        if not course_body:
            return
        target = None
        for c in db.scalars(select(Course)).all():
            if "스마트팜" in (c.name or ""):
                target = c
                break
        if not target:
            print("WARN: 스마트팜 과정 없음 — 공통만 저장함")
            return
        setup = db.get(CourseSetup, target.id)
        if not setup:
            setup = CourseSetup(course_id=target.id)
            db.add(setup)
        setup.course_prompt = course_body
        setup.prompt_manual = True
        setup.updated_at = datetime.now(timezone.utc)
        db.commit()
        print("course prompt saved:", target.id, target.name, "len=", len(setup.course_prompt or ""))
    finally:
        db.close()
    print("OK")


if __name__ == "__main__":
    main()
