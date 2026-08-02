"""로그인·회원가입 HTML + 세션."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import get_session_user_id
from ..config import settings
from ..db import get_db
from ..models import User
from ..passwords import hash_password, verify_password
from .admin import log_access

router = APIRouter(tags=["auth"])


def _page(title: str, body: str, error: str = "", ok: str = "") -> str:
    msg = ""
    if ok:
        msg += f'<p class="ok">{ok}</p>'
    if error:
        msg += f'<p class="err">{error}</p>'
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · 러닝플로우</title>
<style>
:root{{--bg:#F0F2F5;--ink:#1A1D23;--muted:#6B7280;--accent:#2F6FED;--accent-ink:#1E4FC7;--rule:#E2E5EA;--exc:#A6392E;}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);
  font-family:"Pretendard Variable",Pretendard,-apple-system,"Malgun Gothic",sans-serif;padding:24px}}
.card{{width:100%;max-width:400px;background:#fff;border:1px solid var(--rule);border-radius:12px;padding:28px 24px}}
.brand{{font-size:12px;font-weight:700;color:var(--accent);letter-spacing:.04em;margin-bottom:8px}}
h1{{font-size:20px;font-weight:750;margin-bottom:6px}}
.sub{{font-size:13px;color:var(--muted);line-height:1.5;margin-bottom:20px}}
label{{display:block;font-size:12px;font-weight:650;color:var(--muted);margin:12px 0 6px}}
input{{width:100%;padding:10px 12px;border:1px solid var(--rule);border-radius:8px;font-size:14px;background:#F7F8FA}}
input:focus{{outline:none;border-color:var(--accent);background:#fff}}
button{{margin-top:18px;width:100%;padding:12px;border:none;border-radius:8px;background:var(--accent);color:#fff;
  font-size:14px;font-weight:700;cursor:pointer}}
button:hover{{background:var(--accent-ink)}}
.err{{margin:0 0 12px;padding:10px 12px;background:#FDECEA;color:var(--exc);border-radius:8px;font-size:13px}}
.ok{{margin:0 0 12px;padding:10px 12px;background:#E8F6EE;color:#1F7A4C;border-radius:8px;font-size:13px}}
.foot{{margin-top:16px;font-size:13px;color:var(--muted);text-align:center}}
.foot a{{color:var(--accent);font-weight:650;text-decoration:none}}
.hint{{font-size:12px;color:var(--muted);line-height:1.45;margin-top:8px}}
code{{font-size:11px;background:#F0F2F5;padding:1px 5px;border-radius:4px}}
</style>
</head><body>
<div class="card">
  <div class="brand">LEARNING FLOW</div>
  <h1>{title}</h1>
  {msg}
  {body}
</div>
</body></html>"""


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = "", ok: str = ""):
    if get_session_user_id(request) is not None:
        return RedirectResponse("/app", status_code=303)
    body = """
  <p class="sub">계정으로 로그인한 뒤 과정·주차 작업 화면으로 들어갑니다.</p>
  <form method="post" action="/login">
    <label>아이디</label>
    <input name="username" autocomplete="username" required autofocus>
    <label>비밀번호</label>
    <input name="password" type="password" autocomplete="current-password" required>
    <button type="submit">로그인</button>
  </form>
  <p class="foot">계정이 없나요? <a href="/register">회원가입</a>
    · <a href="/reset-password">비밀번호 재설정</a></p>
"""
    return HTMLResponse(_page("로그인", body, error=error, ok=ok))


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    name = username.strip()
    user = db.scalar(select(User).where(User.username == name))
    if not user or not verify_password(password, user.password_hash):
        return login_page(request, error="아이디 또는 비밀번호가 올바르지 않습니다.")
    if name in settings.admin_name_set() and not user.is_admin:
        user.is_admin = True
        db.commit()
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    log_access(db, request, user, "login")
    return RedirectResponse("/app", status_code=303)


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, error: str = ""):
    if get_session_user_id(request) is not None:
        return RedirectResponse("/app", status_code=303)
    body = """
  <p class="sub">테스트용 간단 계정입니다. 아이디·비밀번호만 등록하면 됩니다.</p>
  <form method="post" action="/register">
    <label>아이디</label>
    <input name="username" autocomplete="username" minlength="2" maxlength="40" required autofocus>
    <label>비밀번호</label>
    <input name="password" type="password" autocomplete="new-password" minlength="4" required>
    <label>비밀번호 확인</label>
    <input name="password2" type="password" autocomplete="new-password" minlength="4" required>
    <button type="submit">계정 만들기</button>
  </form>
  <p class="foot">이미 계정이 있나요? <a href="/login">로그인</a>
    · <a href="/reset-password">비밀번호 재설정</a></p>
"""
    return HTMLResponse(_page("회원가입", body, error))


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(request: Request, error: str = ""):
    if get_session_user_id(request) is not None:
        return RedirectResponse("/app", status_code=303)
    body = """
  <p class="sub">아이디와 재설정 키로 새 비밀번호를 설정합니다.</p>
  <form method="post" action="/reset-password">
    <label>아이디</label>
    <input name="username" autocomplete="username" required autofocus>
    <label>새 비밀번호</label>
    <input name="password" type="password" autocomplete="new-password" minlength="4" required>
    <label>새 비밀번호 확인</label>
    <input name="password2" type="password" autocomplete="new-password" minlength="4" required>
    <label>재설정 키</label>
    <input name="reset_key" type="password" autocomplete="off" required placeholder="서버 APP_PASSWORD">
    <p class="hint">재설정 키는 서버 <code>.env</code> 의 <b>APP_PASSWORD</b> 값입니다. (기본 설치면 change-me)</p>
    <button type="submit">비밀번호 바꾸기</button>
  </form>
  <p class="foot"><a href="/login">로그인</a> · <a href="/register">회원가입</a></p>
"""
    return HTMLResponse(_page("비밀번호 재설정", body, error))


@router.post("/reset-password")
def reset_password_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    reset_key: str = Form(...),
    db: Session = Depends(get_db),
):
    name = username.strip()
    if reset_key != settings.app_password:
        return reset_password_page(request, error="재설정 키가 올바르지 않습니다.")
    if len(password) < 4:
        return reset_password_page(request, error="비밀번호는 4자 이상이어야 합니다.")
    if password != password2:
        return reset_password_page(request, error="비밀번호 확인이 일치하지 않습니다.")
    user = db.scalar(select(User).where(User.username == name))
    if not user:
        return reset_password_page(request, error="해당 아이디를 찾을 수 없습니다.")
    user.password_hash = hash_password(password)
    if name in settings.admin_name_set() and not user.is_admin:
        user.is_admin = True
    db.commit()
    log_access(db, request, user, "password_reset")
    return login_page(request, ok="비밀번호를 바꿨습니다. 새 비밀번호로 로그인해 주세요.")


@router.post("/register")
def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    db: Session = Depends(get_db),
):
    name = username.strip()
    if len(name) < 2:
        return register_page(request, error="아이디는 2자 이상이어야 합니다.")
    if len(password) < 4:
        return register_page(request, error="비밀번호는 4자 이상이어야 합니다.")
    if password != password2:
        return register_page(request, error="비밀번호 확인이 일치하지 않습니다.")
    exists = db.scalar(select(func.count()).select_from(User).where(User.username == name))
    if exists:
        return register_page(request, error="이미 사용 중인 아이디입니다.")
    n_users = db.scalar(select(func.count()).select_from(User)) or 0
    # 첫 가입자 또는 ADMIN_USERNAMES 에 있으면 관리자
    make_admin = (n_users == 0) or (name in settings.admin_name_set())
    user = User(username=name, password_hash=hash_password(password), is_admin=make_admin)
    db.add(user)
    db.commit()
    db.refresh(user)
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    log_access(db, request, user, "login")
    return RedirectResponse("/app", status_code=303)


@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    uid = get_session_user_id(request)
    user = db.get(User, uid) if uid else None
    if user:
        log_access(db, request, user, "logout")
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/api/me")
def me(request: Request, db: Session = Depends(get_db)):
    uid = get_session_user_id(request)
    if uid is None:
        return {"ok": False, "user": None}
    user = db.get(User, uid)
    if not user:
        return {"ok": False, "user": None}
    return {
        "ok": True,
        "user": {"id": user.id, "username": user.username, "is_admin": bool(user.is_admin)},
    }
