from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models import Department, Employee
from app.schemas import DepartmentOut, EmployeeOut

router = APIRouter(prefix="/api/org", tags=["org"])


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[Employee, Depends(get_current_user)],
):
    return db.query(Department).order_by(Department.name).all()


@router.get("/employees", response_model=list[EmployeeOut])
def list_employees(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[Employee, Depends(get_current_user)],
):
    return (
        db.query(Employee)
        .options(joinedload(Employee.department))
        .filter(Employee.is_active == True)  # noqa: E712
        .order_by(Employee.employee_id)
        .all()
    )
