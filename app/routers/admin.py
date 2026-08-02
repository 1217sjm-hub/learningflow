"""관리자: 접속·토큰·한화 집계 + 공통 프롬프트 관리."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..auth import get_session_user_id, require_admin, require_login
from ..config import settings
from ..db import get_db
from ..importers import upsert_prompt_version
from ..models import AccessLog, PromptVersion, UsageEvent, User, utcnow

router = APIRouter(tags=["admin"])


class UsageIn(BaseModel):
    model: str = ""
    kind: str = "claude"
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_create_tokens: int = 0
    usd: float = 0.0
    krw: int | None = None
    usd_krw_rate: float | None = None


class PromptVersionIn(BaseModel):
    version: str = Field(min_length=1, max_length=40)
    body: str = ""
    notes: str = ""
    make_default: bool = False


def _client_ip(request: Request) -> str:
    xf = request.headers.get("x-forwarded-for")
    if xf:
        return xf.split(",")[0].strip()
    if request.client:
        return request.client.host or ""
    return ""


def log_access(db: Session, request: Request, user: User | None, action: str) -> None:
    db.add(
        AccessLog(
            user_id=user.id if user else None,
            username=(user.username if user else "") or "",
            action=action,
            ip=_client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:400],
            created_at=utcnow(),
        )
    )
    db.commit()


def _prompt_to_dict(row: PromptVersion) -> dict[str, Any]:
    return {
        "id": row.id,
        "version": row.version or "",
        "body": row.body or "",
        "notes": row.notes or "",
        "is_default": bool(row.is_default),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("/api/usage")
def post_usage(
    body: UsageIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    rate = float(body.usd_krw_rate if body.usd_krw_rate is not None else settings.usd_krw)
    usd = float(body.usd or 0)
    krw = int(body.krw if body.krw is not None else round(usd * rate))
    ev = UsageEvent(
        user_id=user.id,
        username=user.username,
        model=(body.model or "")[:80],
        kind=(body.kind or "claude")[:40],
        input_tokens=int(body.input_tokens or 0),
        output_tokens=int(body.output_tokens or 0),
        cache_read_tokens=int(body.cache_read_tokens or 0),
        cache_create_tokens=int(body.cache_create_tokens or 0),
        usd=usd,
        krw=krw,
        usd_krw_rate=rate,
        created_at=utcnow(),
    )
    db.add(ev)
    db.commit()
    return {"ok": True, "id": ev.id}


@router.get("/api/prompt-versions")
def list_prompt_versions(
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    rows = db.scalars(
        select(PromptVersion).order_by(desc(PromptVersion.is_default), desc(PromptVersion.created_at))
    ).all()
    return {"ok": True, "items": [_prompt_to_dict(r) for r in rows]}


@router.get("/api/prompt-versions/default")
def get_default_prompt_version(
    db: Session = Depends(get_db),
    _user: User = Depends(require_login),
):
    row = db.scalar(select(PromptVersion).where(PromptVersion.is_default.is_(True)))
    if not row:
        row = db.scalar(select(PromptVersion).order_by(desc(PromptVersion.created_at)).limit(1))
    if not row:
        return {"ok": True, "item": None}
    return {"ok": True, "item": _prompt_to_dict(row)}


@router.post("/api/prompt-versions")
def save_prompt_version(
    body: PromptVersionIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    ver = (body.version or "").strip()
    if not ver:
        raise HTTPException(status_code=400, detail="버전을 적어 주세요.")
    # 첫 저장이면 자동으로 기본 지정
    existing_n = db.scalar(select(PromptVersion.id).limit(1))
    make_default = bool(body.make_default) or existing_n is None
    upsert_prompt_version(
        db,
        ver,
        body.body or "",
        notes=(body.notes or "").strip()[:500],
        make_default=make_default,
    )
    row = db.scalar(select(PromptVersion).where(PromptVersion.version == ver))
    return {"ok": True, "item": _prompt_to_dict(row) if row else None}


@router.put("/api/prompt-versions/{version}/default")
def set_default_prompt_version(
    version: str,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    row = db.scalar(select(PromptVersion).where(PromptVersion.version == version))
    if not row:
        raise HTTPException(status_code=404, detail="버전을 찾을 수 없습니다.")
    for other in db.scalars(select(PromptVersion)).all():
        other.is_default = other.id == row.id
    db.commit()
    return {"ok": True, "item": _prompt_to_dict(row)}


def _fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone()
    return local.strftime("%Y-%m-%d %H:%M:%S")


def _admin_html(
    totals: dict[str, Any],
    by_user: list[dict[str, Any]],
    access_rows: list[AccessLog],
    usage_rows: list[UsageEvent],
    prompt_rows: list[PromptVersion],
    me: User,
) -> str:
    bu = "".join(
        f"<tr><td>{escape(r['username'])}</td><td>{r['calls']}</td>"
        f"<td>{r['input_tokens']:,}</td><td>{r['output_tokens']:,}</td>"
        f"<td>${r['usd']:.4f}</td><td>₩{r['krw']:,}</td></tr>"
        for r in by_user
    ) or "<tr><td colspan='6' class='empty'>아직 사용 기록이 없습니다.</td></tr>"

    acc = "".join(
        f"<tr><td>{_fmt_dt(a.created_at)}</td><td>{escape(a.username)}</td>"
        f"<td>{escape(a.action)}</td><td>{escape(a.ip)}</td></tr>"
        for a in access_rows
    ) or "<tr><td colspan='4' class='empty'>접속 기록이 없습니다.</td></tr>"

    use = "".join(
        f"<tr><td>{_fmt_dt(u.created_at)}</td><td>{escape(u.username)}</td>"
        f"<td>{escape(u.model)}</td><td>{u.input_tokens + u.cache_read_tokens + u.cache_create_tokens:,}</td>"
        f"<td>{u.output_tokens:,}</td><td>${u.usd:.4f}</td><td>₩{u.krw:,}</td></tr>"
        for u in usage_rows
    ) or "<tr><td colspan='7' class='empty'>토큰 사용 기록이 없습니다. 앱에서 Claude를 호출하면 쌓입니다.</td></tr>"

    prompts_json = json.dumps([_prompt_to_dict(r) for r in prompt_rows], ensure_ascii=False)

    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=1280">
<title>관리자 · 러닝플로우</title>
<style>
:root{{--bg:#F0F2F5;--ink:#1A1D23;--muted:#6B7280;--accent:#2F6FED;--rule:#E2E5EA;--surface:#fff;--field:#F3F4F6}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--ink);font-family:"Pretendard Variable",Pretendard,-apple-system,"Malgun Gothic",sans-serif;padding:20px 28px}}
.top{{display:flex;align-items:center;gap:12px;margin-bottom:18px}}
.top h1{{font-size:18px;font-weight:750}}
.top .spacer{{flex:1}}
.top a{{font-size:13px;font-weight:650;color:var(--accent);text-decoration:none;margin-left:12px}}
.hint{{font-size:12px;color:var(--muted);margin-bottom:16px;line-height:1.5}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}}
.card{{background:var(--surface);border:1px solid var(--rule);border-radius:10px;padding:14px 16px}}
.card .lbl{{font-size:11px;font-weight:700;color:var(--muted);letter-spacing:.04em}}
.card .val{{font-size:22px;font-weight:750;margin-top:6px}}
.card .sub{{font-size:12px;color:var(--muted);margin-top:4px}}
section{{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:20px 24px;margin-bottom:14px}}
section h2{{font-size:14px;font-weight:750;margin-bottom:10px}}
section .sec-desc{{font-size:12px;color:var(--muted);line-height:1.5;margin:-2px 0 14px}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}
th,td{{padding:8px 10px;border-bottom:1px solid var(--rule);text-align:left}}
th{{font-size:11px;color:var(--muted);font-weight:700}}
td.empty{{color:var(--muted);text-align:center;padding:20px}}
.prompt-grid{{display:grid;grid-template-columns:minmax(240px,320px) 1fr;gap:18px;align-items:start}}
@media (max-width:980px){{.prompt-grid{{grid-template-columns:1fr}}}}
#pv_table tbody tr{{cursor:pointer}}
#pv_table tbody tr:hover{{background:#F7F9FC}}
#pv_table tbody tr.on{{background:#EAF1FF}}
.badge{{display:inline-block;padding:2px 7px;border-radius:999px;font-size:11px;font-weight:700;background:#EAF1FF;color:#1A4FD6}}
.pv-form label{{display:block;font-size:11px;font-weight:700;color:var(--muted);margin:0 0 5px}}
.pv-form .row{{margin-bottom:12px}}
.pv-form input[type=text]{{width:100%;border:1px solid var(--rule);border-radius:8px;padding:9px 11px;font:inherit;font-size:13px;background:var(--field)}}
.pv-form textarea{{width:100%;min-height:320px;border:1px solid var(--rule);border-radius:8px;padding:12px;font-family:ui-monospace,Consolas,monospace;font-size:12px;line-height:1.55;background:var(--field);resize:vertical}}
.pv-form input:focus,.pv-form textarea:focus{{outline:2px solid rgba(47,111,237,.25);border-color:var(--accent);background:#fff}}
.pv-check{{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--ink);font-weight:500;margin:4px 0 14px}}
.pv-actions{{display:flex;flex-wrap:wrap;gap:8px;align-items:center}}
.pv-actions button{{border:1px solid var(--rule);background:var(--field);color:var(--ink);border-radius:999px;padding:8px 14px;font:inherit;font-size:13px;font-weight:600;cursor:pointer}}
.pv-actions button.pri{{background:var(--accent);border-color:var(--accent);color:#fff}}
.pv-actions button:hover{{opacity:.92}}
#pv_msg{{font-size:12px;color:var(--muted);margin-left:4px}}
#pv_msg.ok{{color:#1F7A4C}}
#pv_msg.err{{color:#C0392B}}
</style></head><body>
<div class="top">
  <h1>관리자 · 접속·토큰·비용</h1>
  <span class="spacer"></span>
  <span style="font-size:12px;color:var(--muted)">{escape(me.username)}</span>
  <a href="/app">작업 화면</a>
  <a href="/logout">로그아웃</a>
</div>
<p class="hint">비용은 Anthropic 공식 MTok 요금표 기준 <b>추정</b>입니다 (환율 약 ₩{settings.usd_krw:,.0f}/USD). 실제 청구와 다를 수 있습니다.
Claude 호출은 아직 브라우저에서 이루어지며, 호출 직후 서버로 사용량이 보고됩니다.</p>
<div class="cards">
  <div class="card"><div class="lbl">총 호출</div><div class="val">{totals['calls']:,}</div></div>
  <div class="card"><div class="lbl">입력 토큰</div><div class="val">{totals['input_tokens']:,}</div>
    <div class="sub">미캐시+캐시읽기+캐시저장</div></div>
  <div class="card"><div class="lbl">출력 토큰</div><div class="val">{totals['output_tokens']:,}</div></div>
  <div class="card"><div class="lbl">추정 비용</div><div class="val">₩{totals['krw']:,}</div>
    <div class="sub">${totals['usd']:.4f}</div></div>
</div>

<section>
  <h2>공통 프롬프트 관리</h2>
  <p class="sec-desc">모든 과정의 AI 분할에 쓰이는 공통 규칙입니다. <b>기본</b>으로 지정한 버전이 작업 화면에 반영됩니다.</p>
  <div class="prompt-grid">
    <div>
      <table id="pv_table"><thead><tr><th>버전</th><th>상태</th><th>메모</th></tr></thead>
      <tbody></tbody></table>
    </div>
    <div class="pv-form">
      <div class="row"><label for="pv_version">버전 태그</label>
        <input id="pv_version" type="text" placeholder="예: v4, v4.1" autocomplete="off"></div>
      <div class="row"><label for="pv_notes">메모</label>
        <input id="pv_notes" type="text" placeholder="변경 요약 (선택)" autocomplete="off"></div>
      <div class="row"><label for="pv_body">프롬프트 본문</label>
        <textarea id="pv_body" placeholder="공통 분할 프롬프트를 입력하세요"></textarea></div>
      <label class="pv-check"><input id="pv_default" type="checkbox"> 이 버전을 기본으로 사용</label>
      <div class="pv-actions">
        <button type="button" class="pri" id="pv_save">저장</button>
        <button type="button" id="pv_new">새 버전</button>
        <button type="button" id="pv_set_default">기본으로 지정</button>
        <span id="pv_msg"></span>
      </div>
    </div>
  </div>
</section>

<section>
  <h2>사용자별 합계</h2>
  <table><thead><tr><th>사용자</th><th>호출</th><th>입력</th><th>출력</th><th>USD</th><th>KRW</th></tr></thead>
  <tbody>{bu}</tbody></table>
</section>
<section>
  <h2>최근 접속</h2>
  <table><thead><tr><th>시각</th><th>사용자</th><th>동작</th><th>IP</th></tr></thead>
  <tbody>{acc}</tbody></table>
</section>
<section>
  <h2>최근 Claude 사용</h2>
  <table><thead><tr><th>시각</th><th>사용자</th><th>모델</th><th>입력</th><th>출력</th><th>USD</th><th>KRW</th></tr></thead>
  <tbody>{use}</tbody></table>
</section>
<script>
const PV_INIT = {prompts_json};
let pvItems = Array.isArray(PV_INIT) ? PV_INIT.slice() : [];
let pvSelected = null;

function esc(s) {{
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}}
function setMsg(text, kind) {{
  const el = document.getElementById('pv_msg');
  if (!el) return;
  el.textContent = text || '';
  el.className = kind || '';
}}
function fillForm(item) {{
  pvSelected = item ? item.version : null;
  document.getElementById('pv_version').value = item ? (item.version || '') : '';
  document.getElementById('pv_notes').value = item ? (item.notes || '') : '';
  document.getElementById('pv_body').value = item ? (item.body || '') : '';
  document.getElementById('pv_default').checked = !!(item && item.is_default);
  renderTable();
}}
function renderTable() {{
  const tb = document.querySelector('#pv_table tbody');
  if (!tb) return;
  if (!pvItems.length) {{
    tb.innerHTML = "<tr><td colspan='3' class='empty'>아직 저장된 버전이 없습니다. 오른쪽에 작성 후 저장하세요.</td></tr>";
    return;
  }}
  tb.innerHTML = pvItems.map(it => {{
    const on = pvSelected === it.version ? ' on' : '';
    const badge = it.is_default ? '<span class="badge">기본</span>' : '';
    return `<tr class="${{on}}" data-ver="${{esc(it.version)}}">
      <td>${{esc(it.version)}}</td><td>${{badge}}</td><td>${{esc(it.notes || '—')}}</td></tr>`;
  }}).join('');
  tb.querySelectorAll('tr[data-ver]').forEach(tr => {{
    tr.onclick = () => {{
      const it = pvItems.find(x => x.version === tr.getAttribute('data-ver'));
      if (it) fillForm(it);
    }};
  }});
}}
async function reloadList() {{
  const res = await fetch('/api/prompt-versions', {{ credentials: 'same-origin', cache: 'no-store' }});
  const data = await res.json().catch(() => null);
  if (!res.ok || !data || !data.ok) throw new Error((data && data.detail) || '목록을 불러오지 못했습니다.');
  pvItems = data.items || [];
  const cur = pvSelected ? pvItems.find(x => x.version === pvSelected) : null;
  const pick = cur || pvItems.find(x => x.is_default) || pvItems[0] || null;
  fillForm(pick);
}}
document.getElementById('pv_new').onclick = () => {{
  fillForm({{ version: '', notes: '', body: '', is_default: !pvItems.length }});
  document.getElementById('pv_version').focus();
  setMsg('새 버전을 입력한 뒤 저장하세요.');
}};
document.getElementById('pv_save').onclick = async () => {{
  const version = document.getElementById('pv_version').value.trim();
  const notes = document.getElementById('pv_notes').value.trim();
  const body = document.getElementById('pv_body').value;
  const make_default = document.getElementById('pv_default').checked;
  if (!version) {{ setMsg('버전 태그를 적어 주세요.', 'err'); return; }}
  setMsg('저장 중…');
  try {{
    const res = await fetch('/api/prompt-versions', {{
      method: 'POST',
      credentials: 'same-origin',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ version, notes, body, make_default }})
    }});
    const data = await res.json().catch(() => null);
    if (!res.ok || !data || !data.ok) throw new Error((data && data.detail) || '저장 실패');
    pvSelected = version;
    await reloadList();
    setMsg('저장했습니다.', 'ok');
  }} catch (e) {{
    setMsg(e.message || '저장 실패', 'err');
  }}
}};
document.getElementById('pv_set_default').onclick = async () => {{
  const version = document.getElementById('pv_version').value.trim();
  if (!version) {{ setMsg('버전을 먼저 선택하거나 저장하세요.', 'err'); return; }}
  setMsg('기본 지정 중…');
  try {{
    const res = await fetch('/api/prompt-versions/' + encodeURIComponent(version) + '/default', {{
      method: 'PUT', credentials: 'same-origin'
    }});
    const data = await res.json().catch(() => null);
    if (!res.ok || !data || !data.ok) throw new Error((data && data.detail) || '기본 지정 실패');
    pvSelected = version;
    await reloadList();
    setMsg('기본 버전으로 지정했습니다.', 'ok');
  }} catch (e) {{
    setMsg(e.message || '기본 지정 실패', 'err');
  }}
}};
(function init() {{
  const pick = pvItems.find(x => x.is_default) || pvItems[0] || null;
  fillForm(pick || {{ version: 'v4', notes: '초기 공통 프롬프트', body: '', is_default: true }});
}})();
</script>
</body></html>"""


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(get_db)):
    uid = get_session_user_id(request)
    if uid is None:
        return RedirectResponse("/login", status_code=303)
    me = db.get(User, uid)
    if not me or not me.is_admin:
        return HTMLResponse(
            "<!doctype html><meta charset=utf-8><p style='font-family:sans-serif;padding:40px'>"
            "관리자만 볼 수 있습니다. <a href='/app'>작업 화면</a></p>",
            status_code=403,
        )

    rows = db.scalars(select(UsageEvent)).all()
    totals = {
        "calls": len(rows),
        "input_tokens": sum(r.input_tokens + r.cache_read_tokens + r.cache_create_tokens for r in rows),
        "output_tokens": sum(r.output_tokens for r in rows),
        "usd": sum(r.usd for r in rows),
        "krw": sum(r.krw for r in rows),
    }

    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        k = r.username or f"user#{r.user_id}"
        a = agg.setdefault(k, {"username": k, "calls": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0, "krw": 0})
        a["calls"] += 1
        a["input_tokens"] += r.input_tokens + r.cache_read_tokens + r.cache_create_tokens
        a["output_tokens"] += r.output_tokens
        a["usd"] += r.usd
        a["krw"] += r.krw
    by_user = sorted(agg.values(), key=lambda x: -x["krw"])

    access_rows = db.scalars(select(AccessLog).order_by(desc(AccessLog.created_at)).limit(50)).all()
    usage_rows = db.scalars(select(UsageEvent).order_by(desc(UsageEvent.created_at)).limit(80)).all()
    prompt_rows = db.scalars(
        select(PromptVersion).order_by(desc(PromptVersion.is_default), desc(PromptVersion.created_at))
    ).all()

    return HTMLResponse(_admin_html(totals, by_user, access_rows, usage_rows, prompt_rows, me))
