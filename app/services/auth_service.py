"""本地用户注册与登录。密码只保存慢哈希，令牌只保存摘要。"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.authz import DEPARTMENTS
from app.db.models import AuthSession, User

PASSWORD_ROUNDS = 200_000
SESSION_DAYS = 7


def register_user(db: Session, username: str, password: str, department: str) -> tuple[User, str]:
    cleaned = _username(username)
    _password(password)
    if department not in DEPARTMENTS:
        raise AppError(422, "invalid_department", "部门必须是算法组、框架组或测试组")
    user = User(username=cleaned, password_hash=hash_password(password), department=department)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "username_taken", "用户名已存在") from None
    db.refresh(user)
    return user, _issue_token(db, user)


def login_user(db: Session, username: str, password: str) -> tuple[User, str]:
    user = db.scalar(select(User).where(User.username == username.strip()))
    if user is None or not verify_password(password, user.password_hash):
        raise AppError(401, "invalid_login", "用户名或密码不正确")
    return user, _issue_token(db, user)


def user_from_token(db: Session, token: str) -> User:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == digest))
    if session is None or session.expires_at <= datetime.now(UTC):
        raise AppError(401, "login_required", "请先登录")
    user = db.get(User, session.user_id)
    if user is None:
        raise AppError(401, "login_required", "请先登录")
    return user


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), PASSWORD_ROUNDS
    )
    return f"pbkdf2_sha256${PASSWORD_ROUNDS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt, digest = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        check = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("ascii"),
            int(rounds),
        ).hex()
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(check, digest)


def _issue_token(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(days=SESSION_DAYS),
        )
    )
    db.commit()
    return token


def _username(value: str) -> str:
    cleaned = value.strip()
    if not 2 <= len(cleaned) <= 32:
        raise AppError(422, "invalid_username", "用户名需要 2 到 32 个字符")
    return cleaned


def _password(value: str) -> None:
    if len(value) < 8:
        raise AppError(422, "invalid_password", "密码至少 8 位")
