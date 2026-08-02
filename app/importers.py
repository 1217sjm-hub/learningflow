"""브라우저 JSON / 파일 → ORM 적재."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Case, Course, Decision, PromptVersion, Run, Scene, UnitSetup, Week, utcnow


def _uid(prefix: str = "id") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def upsert_course_lib(db: Session, lib: dict[str, Any], *, replace_weeks: bool = True) -> list[str]:
    """lf_course_lib_v1 형태를 courses+weeks로 넣는다. 반환: course_id 목록."""
    courses = lib.get("courses") or []
    ids: list[str] = []
    for raw in courses:
        cid = str(raw.get("id") or _uid("c"))
        course = db.get(Course, cid)
        if not course:
            course = Course(id=cid)
            db.add(course)
        course.vendor = (raw.get("vendor") or "").strip()
        course.name = (raw.get("course") or raw.get("name") or "").strip()
        course.edu_type = (raw.get("edu") or raw.get("edu_type") or "").strip()
        course.target = (raw.get("target") or "").strip()
        week_count = int(raw.get("weekCount") or raw.get("week_count") or 0)
        units = raw.get("units") or []
        if week_count < 1:
            week_count = len(units)
        course.week_count = week_count
        course.updated_at = utcnow()
        ids.append(cid)

        if replace_weeks:
            # 기존 주차 삭제 후 재생성 (테스트 단계 단순화)
            for w in list(course.weeks):
                db.delete(w)
            db.flush()

        for u in units:
            wid = str(u.get("id") or _uid("u"))
            week_no = u.get("week")
            label = str(u.get("unit") or "")
            if week_no is None:
                m = re.match(r"^(\d+)\s*주차", label)
                week_no = int(m.group(1)) if m else 0
            session_no = u.get("session")
            if session_no is None:
                session_no = u.get("session_no")
            if session_no is None:
                m2 = re.search(r"(\d+)\s*차시", label)
                session_no = int(m2.group(1)) if m2 else 1
            week = db.get(Week, wid)
            if not week:
                week = Week(id=wid, course_id=cid)
                db.add(week)
            week.course_id = cid
            week.week_no = int(week_no or 0)
            week.session_no = int(session_no or 1)
            week.label = (
                u.get("unit")
                or (f"{week.week_no}주차 {week.session_no}차시" if week.week_no else "")
            ).strip()
            week.title = (u.get("unit_title") or u.get("title") or "").strip()
            week.week_title = (u.get("week_title") or "").strip()
            week.updated_at = utcnow()
    db.commit()
    return ids


def upsert_unit_draft(db: Session, draft: dict[str, Any], *, week_id: str | None = None) -> str:
    """lf_setup_draft / lf_unit_draft_* → unit_setups."""
    wid = week_id or draft.get("unitId")
    if not wid:
        raise ValueError("week_id 또는 draft.unitId 가 필요합니다.")
    week = db.get(Week, wid)
    if not week:
        raise ValueError(f"weeks 에 id={wid} 가 없습니다. 과정 라이브러리를 먼저 import 하세요.")

    setup = week.unit_setup
    if not setup:
        setup = UnitSetup(id=_uid("us"), week_id=wid)
        db.add(setup)

    setup.pages_json = draft.get("pageRows")
    setup.vars_json = draft.get("vars")
    setup.course_prompt = draft.get("course_rules") or ""
    setup.prompt_manual = bool(draft.get("manual"))
    setup.source_file = draft.get("hwpName") or ""
    setup.source_paras_json = draft.get("paras") if isinstance(draft.get("paras"), list) else None
    # 전체 draft 백업(scenes 등)
    setup.draft_json = {
        k: draft.get(k)
        for k in (
            "v", "meta", "appStage", "courseId", "unitId", "wizardPhase", "setupPage",
            "hasParas", "hasScenes", "cid", "aiUsed", "updatedAt",
        )
        if k in draft
    }
    if isinstance(draft.get("scenes"), list):
        setup.draft_json["scenes_count"] = len(draft["scenes"])
    setup.updated_at = utcnow()
    db.commit()
    return setup.id


def upsert_prompt_version(
    db: Session,
    version: str,
    body: str,
    *,
    notes: str = "",
    make_default: bool = False,
) -> int:
    row = db.scalar(select(PromptVersion).where(PromptVersion.version == version))
    if not row:
        row = PromptVersion(version=version)
        db.add(row)
    row.body = body
    row.notes = notes
    if make_default:
        for other in db.scalars(select(PromptVersion)).all():
            other.is_default = False
        row.is_default = True
    db.commit()
    return row.id


def import_jsonl_export(db: Session, text: str, *, run_id: str | None = None) -> tuple[str, str]:
    """tagger .jsonl 텍스트 → Case + Run + Decision(+Scene). 반환 (case_id, run_id)."""
    meta: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("__meta"):
            meta = obj["__meta"]
        elif isinstance(obj, dict) and obj.get("id"):
            rows.append(obj)

    if not meta:
        raise ValueError("jsonl 첫 행에 __meta 가 없습니다.")

    case_id = str(meta.get("case_id") or meta.get("cid") or _uid("case"))
    mode = str(meta.get("_mode") or "tag")
    paras = meta.get("_source_paras")
    source_text = ""
    if isinstance(paras, list):
        source_text = "\n".join(str(p) for p in paras)

    case = db.get(Case, case_id)
    if not case:
        case = Case(id=case_id)
        db.add(case)
    case.title = (meta.get("title") or "").strip()
    case.source_text = source_text
    case.source_paras_json = paras if isinstance(paras, list) else None
    case.meta_json = {k: v for k, v in meta.items() if not str(k).startswith("_")}
    case.is_benchmark = bool(meta.get("is_benchmark") or meta.get("holdout") is False and meta.get("schema"))

    rid = run_id or _uid("run")
    run = Run(
        id=rid,
        case_id=case_id,
        prompt_version=str(meta.get("prompt_version") or ""),
        model=str(meta.get("model") or ""),
        input_hash=_hash_text(source_text) if source_text else "",
        status="done",
        mode=mode,
        revisions_json=meta.get("_revisions") if isinstance(meta.get("_revisions"), list) else None,
    )
    db.add(run)

    scene_count = 0
    for row in rows:
        dkey = str(row.get("id"))
        db.add(
            Decision(
                decision_key=dkey,
                run_id=rid,
                relation=str(row.get("relation") or ""),
                kind=str(row.get("kind") or ""),
                sim=float(row["sim"]) if row.get("sim") is not None else None,
                reason_text=str(row.get("reason_text") or row.get("reason") or ""),
                payload_json=row,
            )
        )
        # cmp: ais 배열을 Scene으로도 펼침
        ais = row.get("ais") or []
        if isinstance(ais, list):
            for sc in ais:
                if not isinstance(sc, dict):
                    continue
                no = int(sc.get("no") or 0)
                if no <= 0:
                    continue
                exists = db.scalar(select(Scene).where(Scene.run_id == rid, Scene.no == no))
                if exists:
                    continue
                db.add(
                    Scene(
                        run_id=rid,
                        no=no,
                        title=str(sc.get("title") or ""),
                        screen_json=sc.get("screen"),
                        narration=str(sc.get("narration") or ""),
                        image_prompt=str(sc.get("image_prompt") or ""),
                        objective_json=sc.get("objective"),
                        source=sc.get("source"),
                        page_slot=str(sc.get("page_slot") or ""),
                        page_kind=str(sc.get("page_kind") or ""),
                        feedback_json=sc.get("feedback"),
                        raw_json=sc,
                    )
                )
                scene_count += 1

    run.ai_scene_count = scene_count
    db.commit()
    return case_id, rid


def import_case_decisions_file(db: Session, path: Path, *, is_benchmark: bool = True) -> tuple[str, str]:
    """files/case_001_decisions_v2.json 형태 import."""
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data.get("meta") or {}
    paras = data.get("source_paras") or []
    decisions = data.get("decisions") or []

    case_id = str(meta.get("case_id") or path.stem)
    source_text = "\n".join(str(p) for p in paras) if isinstance(paras, list) else ""

    case = db.get(Case, case_id)
    if not case:
        case = Case(id=case_id)
        db.add(case)
    case.title = str(meta.get("title") or case_id)
    case.source_text = source_text
    case.source_paras_json = paras if isinstance(paras, list) else None
    case.expected_json = {"decisions_count": len(decisions), "slide_count": meta.get("slide_count")}
    case.meta_json = meta
    case.is_benchmark = is_benchmark

    rid = _uid("run")
    run = Run(
        id=rid,
        case_id=case_id,
        prompt_version=str(meta.get("schema") or "decisions"),
        model="",
        input_hash=_hash_text(source_text) if source_text else "",
        ai_scene_count=0,
        status="done",
        mode="tag",
    )
    db.add(run)

    for row in decisions:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        db.add(
            Decision(
                decision_key=str(row["id"]),
                run_id=rid,
                relation=str(row.get("relation") or ""),
                kind="",
                sim=None,
                reason_text=str(row.get("reason_text") or ""),
                payload_json=row,
            )
        )
    db.commit()
    return case_id, rid


def load_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
