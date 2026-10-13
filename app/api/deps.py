"""从 Authorization 头解析当前用户。缺少令牌和无效令牌都要拒绝。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.db.models import User
from app.db.session import get_db
from app.services.auth_service import user_from_token


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AppError(401, "login_required", "请先登录")
    return token.strip()


def get_optional_user(
    db: Session = Depends(get_db),
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    token = _bearer(authorization)
    if token is None:
        return None
    return user_from_token(db, token)


def get_current_user(
    db: Session = Depends(get_db),
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    token = _bearer(authorization)
    if token is None:
        raise AppError(401, "login_required", "请先登录")
    return user_from_token(db, token)
