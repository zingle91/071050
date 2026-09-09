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


def _emp_nodes(emps: list[Employee], favs: set[int]) -> list[OrgTreeEmployee]:
    active = sorted([e for e in emps if e.is_active], key=lambda e: e.employee_id)
    return [
        OrgTreeEmployee(
            id=e.id,
            employee_id=e.employee_id,
            name=e.name,
            is_bot=e.is_bot,
            is_favorite=e.id in favs,
        )
        for e in active
    ]


def _build_dept_node(
    dept: Department,
    children_map: dict[int, list[Department]],
    favs: set[int],
    *,
    is_group: bool = False,
) -> OrgTreeNode:
    """Hierarchical node: parent above children; employees belong to this unit only."""
    kids = sorted(children_map.get(dept.id, []), key=lambda d: d.name)
    return OrgTreeNode(
        id=dept.id,
        name=dept.name,
        code=dept.code,
        node_type="group" if is_group else "department",
        # Group root (One2그룹) typically has no direct employees; depts do.
        employees=[] if is_group else _emp_nodes(list(dept.employees or []), favs),
        children=[_build_dept_node(c, children_map, favs) for c in kids],
    )


@router.get("/tree", response_model=OrgTreeNode)
def org_tree(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    """조직도: One2그룹 루트 아래 parent_id 기준 계층 트리 (세로 트리)."""
    favs = _fav_ids(db, current_user.id)
    all_depts = (
        db.query(Department)
        .options(joinedload(Department.employees))
        .order_by(Department.name)
        .all()
    )
    by_id = {d.id: d for d in all_depts}
    root = next((d for d in all_depts if d.code == "ONE2"), None)

    children_map: dict[int, list[Department]] = {}
    orphans: list[Department] = []
    for d in all_depts:
        if root and d.id == root.id:
            continue
        parent_id = d.parent_id
        if parent_id is not None and parent_id in by_id:
            children_map.setdefault(parent_id, []).append(d)
        else:
            orphans.append(d)

    if root:
        # Attach orphans under root so nothing is lost
        if orphans:
            children_map.setdefault(root.id, []).extend(orphans)
        return _build_dept_node(root, children_map, favs, is_group=True)

    # No ONE2 root: synthesize virtual group
    top = orphans or [d for d in all_depts if d.parent_id is None]
    return OrgTreeNode(
        id=None,
        name="One2그룹",
        code="ONE2",
        node_type="group",
        employees=[],
        children=[_build_dept_node(d, children_map, favs) for d in sorted(top, key=lambda x: x.name)],
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
