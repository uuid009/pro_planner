from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.authz import DEPARTMENT_LABELS
from app.db.models import User
from app.db.session import get_db
from app.services.auth_service import login_user, register_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    department: Literal["algorithm", "framework", "testing"]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: str
    username: str
    department: str
    department_label: str


class AuthOut(BaseModel):
    token: str
    user: UserOut


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        username=user.username,
        department=user.department,
        department_label=DEPARTMENT_LABELS[user.department],
    )


@router.post("/register", response_model=AuthOut, status_code=201)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    user, token = register_user(db, payload.username, payload.password, payload.department)
    return AuthOut(token=token, user=_user_out(user))


@router.post("/login", response_model=AuthOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user, token = login_user(db, payload.username, payload.password)
    return AuthOut(token=token, user=_user_out(user))
