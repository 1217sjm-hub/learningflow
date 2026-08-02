from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import User


def get_session_user_id(request: Request) -> int | None:
    uid = request.session.get("user_id")
    if uid is None:
        return None
    try:
        return int(uid)
    except (TypeError, ValueError):
        return None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    uid = get_session_user_id(request)
    if uid is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    user = db.get(User, uid)
    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user


def require_login(user: User = Depends(get_current_user)) -> User:
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="관리자만 접근할 수 있습니다.")
    return user
