"""화면 피드백·태깅 작업 저장 — Case + Run + Decision(+Scene).

보드 버전: 차시당 최근 3개만 유지(현재 + 이전 복구 2회).
- as_new_version=True  → 새 버전 생성 후 오래된 것 삭제
- 기본 저장           → 지금 열린 버전만 갱신
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import require_login
from ..db import get_db
from ..models import Case, Course, Decision, Run, Scene, Score, User, Week

router = APIRouter(prefix="/api/work", tags=["work"], dependencies=[Depends(require_login)])

BOARD_VERSION_KEEP = 3  # 현재 포함 최대 3개 (= 이전 복구 2회)


def _safe_id(raw: str, prefix: str) -> str:
    s = re.sub(r"[^\w가-힣\-]+", "_", str(raw or "").strip())[:72]
    return s or f"{prefix}_anon"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:40]


def _run_id_for_version(case_id: str, ver: int) -> str:
    """run.id 길이 한도(64) 안에서 버전별 고유 id."""
    digest = hashlib.sha1(case_id.encode("utf-8")).hexdigest()[:16]
    return f"wv_{digest}_v{int(ver)}"[:64]


def _legacy_run_id(case_id: str) -> str:
    return f"work_{case_id}"[:64]


def _upsert_scenes(db: Session, run_id: str, rows: list[dict[str, Any]]) -> int:
    scene_count = 0
    for row in rows:
        ais = row.get("ais") or []
        if not isinstance(ais, list):
            continue
        for sc in ais:
            if not isinstance(sc, dict):
                continue
            no = int(sc.get("no") or 0)
            if no <= 0:
                continue
            exists = db.scalar(select(Scene).where(Scene.run_id == run_id, Scene.no == no))
            if exists:
                exists.title = str(sc.get("title") or "")
                exists.screen_json = sc.get("screen")
                exists.narration = str(sc.get("narration") or "")
                exists.image_prompt = str(sc.get("image_prompt") or "")
                exists.objective_json = sc.get("objective")
                exists.source = sc.get("source")
                exists.page_slot = str(sc.get("page_slot") or "")
                exists.page_kind = str(sc.get("page_kind") or "")
                exists.feedback_json = sc.get("feedback")
                exists.raw_json = sc
            else:
                db.add(
                    Scene(
                        run_id=run_id,
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
    return scene_count


def _delete_run(db: Session, run: Run) -> None:
    score = db.scalar(select(Score).where(Score.run_id == run.id))
    if score:
        db.delete(score)
    for d in list(run.decisions):
        db.delete(d)
    for s in list(run.scenes):
        db.delete(s)
    db.delete(run)
    db.flush()


def _board_meta(case: Case) -> dict[str, Any]:
    meta = dict(case.meta_json or {}) if isinstance(case.meta_json, dict) else {}
    return meta


def _set_board_meta(case: Case, **kwargs: Any) -> None:
    meta = _board_meta(case)
    meta.update(kwargs)
    case.meta_json = meta


def _list_versioned_runs(db: Session, case: Case) -> list[Run]:
    """버전 번호가 있는 cmp Run + 레거시 work_ 런."""
    runs = db.scalars(
        select(Run)
        .options(selectinload(Run.decisions), selectinload(Run.scenes))
        .where(Run.case_id == case.id, Run.mode == "cmp")
        .order_by(Run.created_at.asc())
    ).all()
    out: list[Run] = []
    for r in runs:
        if r.board_version and r.board_version > 0:
            out.append(r)
        elif r.id == _legacy_run_id(case.id) or r.id.startswith("work_"):
            # 레거시 → v1로 승격 표기
            if not r.board_version:
                r.board_version = 1
            out.append(r)
    out.sort(key=lambda x: int(x.board_version or 0))
    return out


def _versions_summary(runs: list[Run], current: int | None) -> list[dict[str, Any]]:
    items = []
    for r in runs:
        ver = int(r.board_version or 0)
        if ver <= 0:
            continue
        items.append({
            "version": ver,
            "run_id": r.id,
            "scenes": int(r.ai_scene_count or 0),
            "prompt_version": r.prompt_version or "",
            "model": r.model or "",
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "is_current": ver == current,
        })
    items.sort(key=lambda x: x["version"], reverse=True)
    return items


def _prune_old_versions(db: Session, case: Case) -> None:
    runs = _list_versioned_runs(db, case)
    if len(runs) <= BOARD_VERSION_KEEP:
        return
    # 오래된 버전부터 삭제
    runs_sorted = sorted(runs, key=lambda r: int(r.board_version or 0))
    drop = runs_sorted[: max(0, len(runs_sorted) - BOARD_VERSION_KEEP)]
    for r in drop:
        _delete_run(db, r)


def _replace_run_payload(
    db: Session,
    run: Run,
    *,
    case_id: str,
    mode: str,
    meta: dict[str, Any],
    rows: list[dict[str, Any]],
    source_text: str,
) -> int:
    for d in list(run.decisions):
        db.delete(d)
    for s in list(run.scenes):
        db.delete(s)
    db.flush()
    run.case_id = case_id
    run.prompt_version = str(meta.get("prompt_version") or run.prompt_version or "")
    run.model = str(meta.get("model") or run.model or "")
    run.input_hash = _hash_text(source_text) if source_text else ""
    run.status = "done"
    run.mode = mode
    run.revisions_json = meta.get("_revisions") if isinstance(meta.get("_revisions"), list) else run.revisions_json

    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        db.add(
            Decision(
                decision_key=str(row.get("id")),
                run_id=run.id,
                relation=str(row.get("relation") or ""),
                kind=str(row.get("kind") or ""),
                sim=float(row["sim"]) if row.get("sim") is not None else None,
                reason_text=str(row.get("reason_text") or row.get("reason") or ""),
                payload_json=row,
            )
        )
    if mode == "cmp":
        run.ai_scene_count = _upsert_scenes(db, run.id, rows)
    else:
        run.ai_scene_count = int(meta.get("ai_scene_count") or 0)
    return int(run.ai_scene_count or 0)


@router.post("/save")
def save_work(body: dict[str, Any], db: Session = Depends(get_db), _: User = Depends(require_login)):
    """보드 저장.

    - as_new_version / meta.as_new_version: 새 보드 버전 생성(롤링 3개)
    - 그 외: 현재(또는 지정) 버전 갱신
    """
    meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
    mode = str(body.get("mode") or meta.get("_mode") or "cmp")
    if mode not in ("cmp", "tag"):
        mode = "cmp"

    as_new = bool(body.get("as_new_version") or meta.get("as_new_version") or meta.get("_as_new_version"))
    target_ver = body.get("board_version")
    if target_ver is None:
        target_ver = meta.get("board_version") or meta.get("_board_version")

    rows = body.get("items") or body.get("decisions") or []
    if not isinstance(rows, list) or not rows:
        raise HTTPException(400, "저장할 항목이 없습니다.")

    paras = body.get("source_paras")
    if paras is None:
        paras = meta.get("_source_paras")
    if not isinstance(paras, list):
        paras = []

    case_id = str(meta.get("case_id") or meta.get("cid") or "").strip()
    if not case_id:
        case_id = _safe_id(meta.get("title") or "case", "case")
    case_id = case_id[:80]

    source_text = "\n".join(str(p) for p in paras)
    course_id = meta.get("course_id") or meta.get("courseId")
    week_id = meta.get("week_id") or meta.get("weekId") or meta.get("unit_id") or meta.get("unitId")
    course_id = str(course_id).strip() if course_id else None
    week_id = str(week_id).strip() if week_id else None
    if course_id and db.get(Course, course_id) is None:
        course_id = None
    if week_id and db.get(Week, week_id) is None:
        week_id = None

    case = db.get(Case, case_id)
    if not case:
        case = Case(id=case_id)
        db.add(case)
    case.title = str(meta.get("title") or case.title or case_id).strip()
    case.source_text = source_text
    case.source_paras_json = paras
    # 보드 버전 키는 메타에 유지 (프론트 전달용 underscore 키는 제외하되 board 필드는 별도 관리)
    base_meta = {k: v for k, v in meta.items() if not str(k).startswith("_")}
    prev_board = _board_meta(case)
    for k in ("board_ver_latest", "board_ver_current"):
        if k in prev_board and k not in base_meta:
            base_meta[k] = prev_board[k]
    case.meta_json = base_meta
    if course_id:
        case.course_id = course_id
    if week_id:
        case.week_id = week_id

    existing = _list_versioned_runs(db, case)
    latest_n = max([int(r.board_version or 0) for r in existing] + [int(prev_board.get("board_ver_latest") or 0)])

    if as_new and mode == "cmp":
        new_ver = latest_n + 1 if latest_n > 0 else 1
        run_id = _run_id_for_version(case_id, new_ver)
        # 혹시 동일 id가 있으면 갱신
        run = db.scalars(
            select(Run)
            .options(selectinload(Run.decisions), selectinload(Run.scenes))
            .where(Run.id == run_id)
        ).first()
        if not run:
            run = Run(
                id=run_id,
                case_id=case_id,
                prompt_version=str(meta.get("prompt_version") or ""),
                model=str(meta.get("model") or ""),
                input_hash="",
                status="done",
                mode=mode,
                board_version=new_ver,
                revisions_json=meta.get("_revisions") if isinstance(meta.get("_revisions"), list) else None,
            )
            db.add(run)
            db.flush()
        else:
            run.board_version = new_ver
        scenes_n = _replace_run_payload(
            db, run, case_id=case_id, mode=mode, meta=meta, rows=rows, source_text=source_text
        )
        _set_board_meta(case, board_ver_latest=new_ver, board_ver_current=new_ver)
        db.flush()
        _prune_old_versions(db, case)
        kept = _list_versioned_runs(db, case)
        db.commit()
        return {
            "ok": True,
            "case_id": case_id,
            "run_id": run.id,
            "mode": mode,
            "board_version": new_ver,
            "as_new_version": True,
            "items": len(rows),
            "scenes": scenes_n,
            "versions": _versions_summary(kept, new_ver),
            "version_keep": BOARD_VERSION_KEEP,
        }

    # 현재 버전 갱신
    cur = None
    if target_ver is not None:
        try:
            cur = int(target_ver)
        except (TypeError, ValueError):
            cur = None
    if cur is None:
        cur = int(prev_board.get("board_ver_current") or latest_n or 0)

    run = None
    if cur > 0:
        run = next((r for r in existing if int(r.board_version or 0) == cur), None)
        if not run:
            rid = _run_id_for_version(case_id, cur)
            run = db.scalars(
                select(Run)
                .options(selectinload(Run.decisions), selectinload(Run.scenes))
                .where(Run.id == rid)
            ).first()

    if not run and existing:
        run = existing[-1]
        cur = int(run.board_version or 1)

    if not run:
        # 첫 저장 — v1 생성
        cur = 1
        run_id = _run_id_for_version(case_id, 1)
        # 레거시 슬롯이 있으면 그걸 v1로 사용
        legacy = db.scalars(
            select(Run)
            .options(selectinload(Run.decisions), selectinload(Run.scenes))
            .where(Run.id == _legacy_run_id(case_id))
        ).first()
        if legacy:
            run = legacy
            run.board_version = 1
        else:
            run = Run(
                id=run_id,
                case_id=case_id,
                prompt_version=str(meta.get("prompt_version") or ""),
                model=str(meta.get("model") or ""),
                input_hash="",
                status="done",
                mode=mode,
                board_version=1,
            )
            db.add(run)
            db.flush()

    scenes_n = _replace_run_payload(
        db, run, case_id=case_id, mode=mode, meta=meta, rows=rows, source_text=source_text
    )
    if not run.board_version:
        run.board_version = cur or 1
        cur = run.board_version
    _set_board_meta(
        case,
        board_ver_latest=max(latest_n, int(run.board_version or 1)),
        board_ver_current=int(run.board_version or 1),
    )
    db.flush()
    kept = _list_versioned_runs(db, case)
    db.commit()
    return {
        "ok": True,
        "case_id": case_id,
        "run_id": run.id,
        "mode": mode,
        "board_version": int(run.board_version or 1),
        "as_new_version": False,
        "items": len(rows),
        "scenes": scenes_n,
        "versions": _versions_summary(kept, int(run.board_version or 1)),
        "version_keep": BOARD_VERSION_KEEP,
    }


def _work_payload_from_run(db: Session, case: Case, run: Run) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for d in sorted(run.decisions, key=lambda x: str(x.decision_key or "")):
        row = dict(d.payload_json) if isinstance(d.payload_json, dict) else {"id": d.decision_key}
        row["id"] = row.get("id") or d.decision_key
        row["kind"] = row.get("kind") or d.kind or ""
        row["sim"] = row.get("sim") if row.get("sim") is not None else d.sim
        row["reason_text"] = d.reason_text or row.get("reason_text") or row.get("reason") or ""
        items.append(row)

    meta = dict(case.meta_json or {})
    meta["case_id"] = case.id
    meta["title"] = case.title or meta.get("title") or case.id
    if case.course_id:
        meta["course_id"] = case.course_id
    if case.week_id:
        meta["week_id"] = case.week_id
    meta["_mode"] = run.mode or "cmp"
    if run.revisions_json:
        meta["_revisions"] = run.revisions_json
    ver = int(run.board_version or 0) or 1
    meta["board_version"] = ver
    meta["_board_version"] = ver

    paras = case.source_paras_json if isinstance(case.source_paras_json, list) else []
    kept = _list_versioned_runs(db, case)
    return {
        "ok": True,
        "case_id": case.id,
        "run_id": run.id,
        "mode": run.mode or "cmp",
        "board_version": ver,
        "meta": meta,
        "items": items,
        "source_paras": paras,
        "versions": _versions_summary(kept, ver),
        "version_keep": BOARD_VERSION_KEEP,
    }


def _pick_run(db: Session, case: Case, version: int | None = None) -> Run | None:
    runs = _list_versioned_runs(db, case)
    if not runs:
        return None
    if version is not None:
        for r in runs:
            if int(r.board_version or 0) == int(version):
                return r
        return None
    # 현재 또는 최신
    meta = _board_meta(case)
    cur = meta.get("board_ver_current")
    if cur is not None:
        for r in runs:
            if int(r.board_version or 0) == int(cur):
                return r
    return runs[-1]


def _work_payload_from_case(db: Session, case: Case, version: int | None = None) -> dict[str, Any] | None:
    run = _pick_run(db, case, version=version)
    if not run or not run.decisions:
        return None
    return _work_payload_from_run(db, case, run)


@router.get("/by-week/{week_id}")
def get_work_by_week(
    week_id: str,
    version: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_login),
):
    """차시(week)에 저장된 AI 분할 보드를 불러온다. ?version=N 으로 특정 버전."""
    case = db.scalars(
        select(Case).where(Case.week_id == week_id).order_by(Case.created_at.desc())
    ).first()
    if not case:
        raise HTTPException(404, "이 차시에 저장된 보드가 없습니다.")
    payload = _work_payload_from_case(db, case, version=version)
    if not payload:
        raise HTTPException(404, "이 차시에 저장된 보드가 없습니다.")
    return payload


@router.get("/by-week/{week_id}/versions")
def list_work_versions_by_week(week_id: str, db: Session = Depends(get_db), _: User = Depends(require_login)):
    case = db.scalars(
        select(Case).where(Case.week_id == week_id).order_by(Case.created_at.desc())
    ).first()
    if not case:
        raise HTTPException(404, "이 차시에 저장된 보드가 없습니다.")
    runs = _list_versioned_runs(db, case)
    meta = _board_meta(case)
    cur = meta.get("board_ver_current")
    if cur is None and runs:
        cur = int(runs[-1].board_version or 1)
    return {
        "ok": True,
        "case_id": case.id,
        "board_version": cur,
        "versions": _versions_summary(runs, int(cur) if cur is not None else None),
        "version_keep": BOARD_VERSION_KEEP,
    }


@router.get("/board-summary-by-course/{course_id}")
def board_summary_by_course(course_id: str, db: Session = Depends(get_db), _: User = Depends(require_login)):
    """과정 안 차시별 보드 현재 버전(사이드바 배지용)."""
    if db.get(Course, course_id) is None:
        raise HTTPException(404, "과정을 찾지 못했습니다.")
    cases = db.scalars(
        select(Case).where(Case.course_id == course_id).order_by(Case.created_at.desc())
    ).all()
    by_week: dict[str, dict[str, Any]] = {}
    for case in cases:
        wid = case.week_id
        if not wid or wid in by_week:
            continue  # 차시당 최신 case 1개
        runs = _list_versioned_runs(db, case)
        if not runs:
            continue
        meta = _board_meta(case)
        cur = meta.get("board_ver_current")
        if cur is None:
            cur = int(runs[-1].board_version or 1)
        by_week[str(wid)] = {
            "case_id": case.id,
            "board_version": int(cur),
            "version_count": len(runs),
            "version_keep": BOARD_VERSION_KEEP,
        }
    return {"ok": True, "course_id": course_id, "by_week": by_week}


@router.get("/by-case/{case_id}")
def get_work_by_case(
    case_id: str,
    version: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_login),
):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "저장된 보드를 찾지 못했습니다.")
    payload = _work_payload_from_case(db, case, version=version)
    if not payload:
        raise HTTPException(404, "저장된 보드를 찾지 못했습니다.")
    return payload
