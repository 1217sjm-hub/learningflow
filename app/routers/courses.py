"""과정·주차·폴더 CRUD — 프론트 lf_course_lib 형태와 호환."""
from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import Session

from ..auth import require_login
from ..course_setup_store import (
    apply_shared_setup_to_course,
    course_query_options,
    shared_setup_from_course,
    shared_setup_meaningful,
)
from ..db import get_db
from ..models import Course, CourseFolder, Week, utcnow
from ..schemas import CourseLibIn, CourseLibOut

router = APIRouter(prefix="/api", tags=["courses"], dependencies=[Depends(require_login)])


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def folder_to_frontend(f: CourseFolder) -> dict[str, Any]:
    return {
        "id": f.id,
        "name": f.name or "",
        "parentId": f.parent_id,
        "sort": f.sort_order or 0,
        "updatedAt": f.updated_at.isoformat() if f.updated_at else None,
    }


def _parse_week_session(data: dict[str, Any]) -> tuple[int | None, int]:
    wno = data.get("week")
    sno = data.get("session")
    if sno is None:
        sno = data.get("session_no")
    label = str(data.get("unit") or "")
    if wno is None:
        m = re.match(r"^(\d+)\s*주차", label)
        wno = int(m.group(1)) if m else None
    if sno is None:
        m2 = re.search(r"(\d+)\s*차시", label)
        sno = int(m2.group(1)) if m2 else 1
    try:
        wno_i = int(wno) if wno is not None else None
    except (TypeError, ValueError):
        wno_i = None
    try:
        sno_i = int(sno) if sno is not None else 1
    except (TypeError, ValueError):
        sno_i = 1
    if sno_i < 1:
        sno_i = 1
    return wno_i, sno_i


def course_to_frontend(c: Course) -> dict[str, Any]:
    weeks = sorted(
        c.weeks or [],
        key=lambda w: (w.week_no or 0, getattr(w, "session_no", 1) or 1, w.id),
    )
    week_nos = {w.week_no for w in weeks if w.week_no}
    shared = shared_setup_from_course(c)
    prompt = ""
    if c.setup and c.setup.course_prompt:
        prompt = c.setup.course_prompt
    else:
        ov = c.overrides_json if isinstance(c.overrides_json, dict) else {}
        prompt = ov.get("prompt", "") or ""
        if not prompt and isinstance(shared, dict):
            prompt = shared.get("course_rules") or ""
    return {
        "id": c.id,
        "vendor": c.vendor or "",
        "course": c.name or "",
        "edu": c.edu_type or "",
        "target": c.target or "",
        "weekCount": c.week_count or (max(week_nos) if week_nos else len(weeks)),
        "folderId": c.folder_id,
        "prompt": prompt,
        "sharedSetup": shared if isinstance(shared, dict) else {},
        "units": [
            {
                "id": w.id,
                "week": w.week_no,
                "session": getattr(w, "session_no", 1) or 1,
                "unit": w.label
                or (
                    f"{w.week_no}주차 {getattr(w, 'session_no', 1) or 1}차시"
                    if w.week_no
                    else ""
                ),
                "unit_title": w.title or "",
                "week_title": getattr(w, "week_title", "") or "",
                "updatedAt": w.updated_at.isoformat() if w.updated_at else None,
            }
            for w in weeks
        ],
        "createdAt": c.created_at.isoformat() if c.created_at else None,
        "updatedAt": c.updated_at.isoformat() if c.updated_at else None,
    }


def _ensure_weeks_on_course(course: Course, week_count: int, units_in: list[Any]) -> None:
    n = int(week_count or 0)
    if n < 1:
        n = 1
    if n > 52:
        n = 52
    course.week_count = n

    incoming_ids: set[str] = set()
    for raw in units_in or []:
        data = raw if isinstance(raw, dict) else raw.model_dump()
        wid = str(data.get("id") or _uid("w"))
        incoming_ids.add(wid)
        wno, sno = _parse_week_session(data)
        if wno is None:
            wno = 1
        w = next((x for x in (course.weeks or []) if x.id == wid), None)
        if not w:
            w = Week(id=wid, course_id=course.id, week_no=wno, session_no=sno)
            course.weeks.append(w)
        w.week_no = int(wno)
        w.session_no = int(sno or 1)
        w.title = str(data.get("unit_title") or data.get("title") or "").strip()
        w.week_title = str(data.get("week_title") or "").strip()
        w.label = str(data.get("unit") or "").strip() or f"{w.week_no}주차 {w.session_no}차시"
        w.updated_at = utcnow()

    # 프론트가 units 전체를 보내면 없는 주차·차시는 제거
    if units_in is not None:
        for w in list(course.weeks or []):
            if w.id not in incoming_ids:
                course.weeks.remove(w)


def _sync_folders(db: Session, folders_in: list[Any]) -> set[str]:
    """폴더 upsert. 페이로드에 없는 폴더는 삭제(과정은 folder_id SET NULL)."""
    incoming: set[str] = set()
    for i, raw in enumerate(folders_in or []):
        data = raw if isinstance(raw, dict) else raw.model_dump()
        fid = str(data.get("id") or _uid("f"))
        incoming.add(fid)
        folder = db.get(CourseFolder, fid)
        if not folder:
            folder = CourseFolder(id=fid)
            db.add(folder)
        folder.name = (data.get("name") or "").strip() or "새 폴더"
        parent = data.get("parentId")
        if parent is None:
            parent = data.get("parent_id")
        folder.parent_id = (str(parent).strip() if parent else None) or None
        sort = data.get("sort")
        if sort is None:
            sort = data.get("sort_order")
        try:
            folder.sort_order = int(sort if sort is not None else i)
        except (TypeError, ValueError):
            folder.sort_order = i
        folder.updated_at = utcnow()

    existing = db.scalars(select(CourseFolder)).all()
    for folder in existing:
        if folder.id not in incoming:
            for c in list(folder.courses or []):
                c.folder_id = None
            db.delete(folder)
    return incoming


@router.get("/course-lib", response_model=CourseLibOut)
def get_course_lib(db: Session = Depends(get_db)):
    folders = db.scalars(select(CourseFolder).order_by(CourseFolder.sort_order.asc(), CourseFolder.name.asc())).all()
    rows = db.scalars(
        select(Course).options(*course_query_options()).order_by(Course.updated_at.desc())
    ).all()
    return CourseLibOut(
        v=2,
        folders=[folder_to_frontend(f) for f in folders],
        courses=[course_to_frontend(c) for c in rows],
        source="db",
    )


@router.put("/course-lib", response_model=CourseLibOut)
def put_course_lib(body: CourseLibIn, db: Session = Depends(get_db)):
    """프론트 전체 라이브러리를 DB 정본으로 반영 (upsert + 없는 과정 삭제 안 함: 명시 삭제 API 사용)."""
    folder_ids = _sync_folders(db, body.folders)
    db.flush()

    for raw in body.courses:
        data = raw.model_dump()
        cid = str(data.get("id") or _uid("c"))
        course = db.scalars(
            select(Course).options(*course_query_options()).where(Course.id == cid)
        ).first()
        if not course:
            course = Course(id=cid)
            db.add(course)
            db.flush()
            course = db.scalars(
                select(Course).options(*course_query_options()).where(Course.id == cid)
            ).first()
        assert course is not None

        course.vendor = (data.get("vendor") or "").strip()
        course.name = (data.get("course") or data.get("name") or "").strip()
        course.edu_type = (data.get("edu") or data.get("edu_type") or "").strip()
        course.target = (data.get("target") or "").strip()

        shared = data.get("sharedSetup")
        if isinstance(shared, dict) and (
            shared_setup_meaningful(shared)
            or course.setup is not None
            or (course.page_rows and len(course.page_rows) > 0)
        ):
            apply_shared_setup_to_course(db, course, shared)
        else:
            # sharedSetup 없으면 prompt 만 overrides 에 백업
            prompt = data.get("prompt") or ""
            if prompt:
                ov = dict(course.overrides_json or {})
                ov["prompt"] = prompt
                if "sharedSetup" in ov:
                    del ov["sharedSetup"]
                course.overrides_json = ov
                flag_modified(course, "overrides_json")

        fid = data.get("folderId")
        if fid is None:
            fid = data.get("folder_id")
        fid = (str(fid).strip() if fid else None) or None
        course.folder_id = fid if fid and fid in folder_ids else None
        week_count = data.get("weekCount")
        if week_count is None:
            week_count = data.get("week_count")
        _ensure_weeks_on_course(course, int(week_count or 0), data.get("units") or [])
        course.updated_at = utcnow()
        if course.overrides_json is not None:
            flag_modified(course, "overrides_json")

    db.commit()
    folders = db.scalars(select(CourseFolder).order_by(CourseFolder.sort_order.asc(), CourseFolder.name.asc())).all()
    rows = db.scalars(
        select(Course).options(*course_query_options()).order_by(Course.updated_at.desc())
    ).all()
    return CourseLibOut(
        v=2,
        folders=[folder_to_frontend(f) for f in folders],
        courses=[course_to_frontend(c) for c in rows],
        source="db",
    )


@router.delete("/courses/{course_id}")
def delete_course(course_id: str, db: Session = Depends(get_db)):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(404, "과정을 찾을 수 없습니다.")
    db.delete(course)
    db.commit()
    return {"ok": True, "id": course_id}


@router.put("/courses/{course_id}/weeks")
def put_weeks(course_id: str, weeks: list[dict[str, Any]], db: Session = Depends(get_db)):
    """주차 제목만 일괄 갱신."""
    course = db.scalars(
        select(Course).options(*course_query_options()).where(Course.id == course_id)
    ).first()
    if not course:
        raise HTTPException(404, "과정을 찾을 수 없습니다.")
    by_id = {str(w.get("id")): w for w in weeks if w.get("id")}
    for w in course.weeks:
        src = by_id.get(w.id)
        if not src:
            continue
        if "unit_title" in src or "title" in src:
            w.title = str(src.get("unit_title") or src.get("title") or "").strip()
        if "unit" in src:
            w.label = str(src.get("unit") or w.label or "")
        w.updated_at = utcnow()
    course.updated_at = utcnow()
    db.commit()
    return {"ok": True, "id": course_id}
