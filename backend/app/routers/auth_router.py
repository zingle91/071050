from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.auth import verify_password, create_access_token, get_current_user
from app.database import get_db
from app.models import Employee
from app.schemas import Token, LoginRequest, EmployeeOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login_form(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
):
    """OAuth2 form login (username = 사번)."""
    user = db.query(Employee).filter(Employee.employee_id == form_data.username).first()
    if not user or user.is_bot or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="사번 또는 비밀번호가 올바르지 않습니다")
    token = create_access_token({"sub": user.employee_id})
    return Token(access_token=token)


@router.post("/login/json", response_model=Token)
def login_json(body: LoginRequest, db: Annotated[Session, Depends(get_db)]):
    user = db.query(Employee).filter(Employee.employee_id == body.employee_id).first()
    if not user or user.is_bot or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="사번 또는 비밀번호가 올바르지 않습니다")
    token = create_access_token({"sub": user.employee_id})
    return Token(access_token=token)


@router.get("/me", response_model=EmployeeOut)
def me(current_user: Annotated[Employee, Depends(get_current_user)]):
    return current_user
