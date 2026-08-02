"""과정 셋팅: sharedSetup(dict) ↔ course_setups / course_page_rows."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import Course, CoursePageRow, CourseSetup, utcnow


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _flag(v: Any, default: bool = True) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return default


def _norm_kind(k: Any) -> str:
    s = str(k or "").replace(" ", "")
    if s == "가변":
        return "가변"
    if "이미지" in s:
        return "이미지"
    return "고정"


def shared_setup_meaningful(shared: Any) -> bool:
    if not isinstance(shared, dict) or not shared:
        return False
    rows = shared.get("pageRows")
    if isinstance(rows, list) and len(rows) > 0:
        return True
    if str(shared.get("course_rules") or "").strip():
        return True
    vars_ = shared.get("vars")
    if isinstance(vars_, dict):
        for v in vars_.values():
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            return True
    return False


def shared_setup_from_course(c: Course) -> dict[str, Any]:
    """정규 테이블 → 프론트 sharedSetup 형태."""
    setup = getattr(c, "setup", None)
    rows = list(getattr(c, "page_rows", None) or [])
    rows.sort(key=lambda r: (r.sort_order or 0, r.id or ""))

    if setup is None and not rows:
        ov = c.overrides_json if isinstance(c.overrides_json, dict) else {}
        legacy = ov.get("sharedSetup")
        if isinstance(legacy, dict):
            return legacy
        return {}

    vars_: dict[str, Any] = {
        "m_author": (setup.author if setup else "") or "",
        "m_author_role": (setup.author_role if setup else "") or "",
        "m_target": c.target or "",
        "m_pages": (setup.pages_text if setup else "") or "",
        "m_tpl_name": (setup.tpl_name if setup else "") or "",
        "m_tpl_analysis": (setup.tpl_analysis if setup else "") or "",
        "m_tpl_meta": (setup.tpl_meta if setup else "[]") or "[]",
        "m_narr_len": (setup.narr_len if setup else "") or "",
        "m_tone": (setup.tone if setup else "") or "",
        "m_forbidden": (setup.forbidden if setup else "") or "",
        "m_img_style": (setup.img_style if setup else "") or "",
        "m_extra_prompt": (setup.extra_prompt if setup else "") or "",
        "m_set_split_first": "1" if (setup.set_split_first if setup else True) else "0",
        "m_set_merge_dup_only": "1" if (setup.set_merge_dup_only if setup else True) else "0",
        "m_set_no_overcompress": "1" if (setup.set_no_overcompress if setup else True) else "0",
        "m_set_keep_wording": "1" if (setup.set_keep_wording if setup else True) else "0",
        "m_set_no_scene_cap": "1" if (setup.set_no_scene_cap if setup else True) else "0",
        "m_set_bullets_wide": "1" if (setup.set_bullets_wide if setup else True) else "0",
    }
    page_rows = [
        {
            "name": r.name or "",
            "kind": _norm_kind(r.kind),
            "note": r.note or "",
            "_tpls": [],
        }
        for r in rows
    ]
    updated = None
    if setup and setup.updated_at:
        updated = setup.updated_at.isoformat()
    return {
        "vars": vars_,
        "pageRows": page_rows,
        "course_rules": (setup.course_prompt if setup else "") or "",
        "manual": bool(setup.prompt_manual) if setup else False,
        "updatedAt": updated,
    }


def apply_shared_setup_to_course(db: Session, course: Course, shared: dict[str, Any] | None) -> None:
    """sharedSetup dict → course_setups / course_page_rows. 의미 없으면 no-op."""
    if not isinstance(shared, dict):
        return
    if not shared_setup_meaningful(shared) and course.setup is None and not (course.page_rows or []):
        return

    vars_ = shared.get("vars") if isinstance(shared.get("vars"), dict) else {}
    setup = course.setup
    if setup is None:
        setup = CourseSetup(course_id=course.id)
        db.add(setup)
        course.setup = setup

    setup.author = str(vars_.get("m_author") or "").strip()
    setup.author_role = str(vars_.get("m_author_role") or "").strip()
    setup.narr_len = str(vars_.get("m_narr_len") or "").strip()
    setup.tone = str(vars_.get("m_tone") or "").strip()
    setup.forbidden = str(vars_.get("m_forbidden") or "").strip()
    setup.img_style = str(vars_.get("m_img_style") or "").strip()
    setup.extra_prompt = str(vars_.get("m_extra_prompt") or "")
    setup.pages_text = str(vars_.get("m_pages") or "")
    setup.tpl_name = str(vars_.get("m_tpl_name") or "").strip()
    setup.tpl_analysis = str(vars_.get("m_tpl_analysis") or "")
    setup.tpl_meta = str(vars_.get("m_tpl_meta") or "[]") or "[]"
    setup.set_split_first = _flag(vars_.get("m_set_split_first"), True)
    setup.set_merge_dup_only = _flag(vars_.get("m_set_merge_dup_only"), True)
    setup.set_no_overcompress = _flag(vars_.get("m_set_no_overcompress"), True)
    setup.set_keep_wording = _flag(vars_.get("m_set_keep_wording"), True)
    setup.set_no_scene_cap = _flag(vars_.get("m_set_no_scene_cap"), True)
    setup.set_bullets_wide = _flag(vars_.get("m_set_bullets_wide"), True)
    setup.course_prompt = str(shared.get("course_rules") or "")
    setup.prompt_manual = bool(shared.get("manual"))
    setup.updated_at = utcnow()

    # courses.target 과 셋팅의 m_target 동기화
    if vars_.get("m_target") is not None:
        t = str(vars_.get("m_target") or "").strip()
        if t:
            course.target = t

    # 페이지 줄 전량 교체
    course.page_rows.clear()
    db.flush()
    raw_rows = shared.get("pageRows") if isinstance(shared.get("pageRows"), list) else []
    for i, r in enumerate(raw_rows):
        if not isinstance(r, dict):
            continue
        course.page_rows.append(
            CoursePageRow(
                id=_uid("pr"),
                course_id=course.id,
                sort_order=i,
                name=str(r.get("name") or "").strip(),
                kind=_norm_kind(r.get("kind")),
                note=str(r.get("note") or ""),
                updated_at=utcnow(),
            )
        )

    # overrides_json 에서는 sharedSetup 제거(정본은 테이블). prompt 백업만 유지.
    ov = dict(course.overrides_json or {})
    if setup.course_prompt:
        ov["prompt"] = setup.course_prompt
    if "sharedSetup" in ov:
        del ov["sharedSetup"]
    course.overrides_json = ov or None
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(course, "overrides_json")


def migrate_legacy_shared_setups(db: Session) -> int:
    """overrides_json.sharedSetup → 정규 테이블. 반환: 이전한 과정 수."""
    courses = db.scalars(
        select(Course).options(selectinload(Course.setup), selectinload(Course.page_rows))
    ).all()
    n = 0
    for c in courses:
        if c.setup is not None or (c.page_rows and len(c.page_rows) > 0):
            continue
        ov = c.overrides_json if isinstance(c.overrides_json, dict) else {}
        shared = ov.get("sharedSetup")
        if not shared_setup_meaningful(shared):
            continue
        apply_shared_setup_to_course(db, c, shared)
        n += 1
    if n:
        db.commit()
    return n


def course_query_options():
    return (
        selectinload(Course.weeks),
        selectinload(Course.setup),
        selectinload(Course.page_rows),
    )
