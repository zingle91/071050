from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models import Department, Employee, FavoriteEmployee
from app.schemas import DepartmentOut, EmployeeOut, OrgTreeNode, OrgTreeEmployee, FavoriteToggleRequest

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


def _fav_ids(db: Session, owner_id: int) -> set[int]:
    rows = (
        db.query(FavoriteEmployee.employee_id)
        .filter(FavoriteEmployee.owner_id == owner_id)
        .all()
    )
    return {r[0] for r in rows}


@router.get("/tree", response_model=OrgTreeNode)
def org_tree(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    """조직도: One2그룹 루트 아래 부서들이 형제, 직원은 부서 하위."""
    favs = _fav_ids(db, current_user.id)
    root = db.query(Department).filter(Department.code == "ONE2").first()

    depts = (
        db.query(Department)
        .options(joinedload(Department.employees))
        .filter(Department.code != "ONE2")
        .order_by(Department.name)
        .all()
    )

    children: list[OrgTreeNode] = []
    for d in depts:
        emps = sorted(
            [e for e in d.employees if e.is_active],
            key=lambda e: e.employee_id,
        )
        children.append(
            OrgTreeNode(
                id=d.id,
                name=d.name,
                code=d.code,
                node_type="department",
                employees=[
                    OrgTreeEmployee(
                        id=e.id,
                        employee_id=e.employee_id,
                        name=e.name,
                        is_bot=e.is_bot,
                        is_favorite=e.id in favs,
                    )
                    for e in emps
                ],
                children=[],
            )
        )

    return OrgTreeNode(
        id=root.id if root else None,
        name=root.name if root else "One2그룹",
        code=root.code if root else "ONE2",
        node_type="group",
        employees=[],
        children=children,
    )


@router.get("/favorites", response_model=list[EmployeeOut])
def list_favorites(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    rows = (
        db.query(FavoriteEmployee)
        .options(
            joinedload(FavoriteEmployee.employee).joinedload(Employee.department)
        )
        .filter(FavoriteEmployee.owner_id == current_user.id)
        .all()
    )
    return [r.employee for r in rows if r.employee and r.employee.is_active]


@router.post("/favorites", response_model=list[EmployeeOut])
def add_favorite(
    body: FavoriteToggleRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    target = db.query(Employee).filter(Employee.id == body.employee_id).first()
    if not target or not target.is_active:
        raise HTTPException(status_code=404, detail="직원을 찾을 수 없습니다")
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="본인은 즐겨찾기에 추가할 수 없습니다")
    existing = (
        db.query(FavoriteEmployee)
        .filter(
            FavoriteEmployee.owner_id == current_user.id,
            FavoriteEmployee.employee_id == body.employee_id,
        )
        .first()
    )
    if not existing:
        db.add(FavoriteEmployee(owner_id=current_user.id, employee_id=body.employee_id))
        db.commit()
    return list_favorites(db, current_user)


@router.delete("/favorites/{employee_id}", response_model=list[EmployeeOut])
def remove_favorite(
    employee_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    row = (
        db.query(FavoriteEmployee)
        .filter(
            FavoriteEmployee.owner_id == current_user.id,
            FavoriteEmployee.employee_id == employee_id,
        )
        .first()
    )
    if row:
        db.delete(row)
        db.commit()
    return list_favorites(db, current_user)
