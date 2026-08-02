"""FastAPI — 로그인 게이트 + 과정/주차 API + 앱 서빙."""
from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .auth import get_session_user_id, require_login
from .config import ROOT, settings
from .db import get_db, init_db
from .models import Case, Course, Decision, Run, Scene, User, Week
from .routers import admin as admin_router
from .routers import auth_pages, courses as courses_router
from .routers import work as work_router

FILES_DIR = ROOT.parent / "files"

app = FastAPI(title="러닝플로우 API", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="lf_session",
    max_age=60 * 60 * 24 * 14,
    same_site="lax",
)

app.include_router(auth_pages.router)
app.include_router(admin_router.router)
app.include_router(courses_router.router)
app.include_router(work_router.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health():
    return {
        "ok": True,
        "version": __version__,
        "auth": "session",
    }


@app.get("/api/stats")
def stats(db: Session = Depends(get_db), _: User = Depends(require_login)):
    return {
        "courses": db.scalar(select(func.count()).select_from(Course)) or 0,
        "weeks": db.scalar(select(func.count()).select_from(Week)) or 0,
        "cases": db.scalar(select(func.count()).select_from(Case)) or 0,
        "runs": db.scalar(select(func.count()).select_from(Run)) or 0,
        "scenes": db.scalar(select(func.count()).select_from(Scene)) or 0,
        "decisions": db.scalar(select(func.count()).select_from(Decision)) or 0,
        "users": db.scalar(select(func.count()).select_from(User)) or 0,
    }


@app.get("/")
def root(request: Request):
    if get_session_user_id(request) is None:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/app", status_code=303)


@app.get("/app")
def app_page(request: Request):
    if get_session_user_id(request) is None:
        return RedirectResponse("/login", status_code=303)
    index = FILES_DIR / "tagger_web.html"
    if index.is_file():
        return FileResponse(index)
    return RedirectResponse("/health")
