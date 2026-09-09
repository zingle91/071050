from sqlalchemy.orm import Session
from app.auth import hash_password
from app.models import Department, Employee, Room, RoomMember, Message, Note, FavoriteEmployee


SEED_PASSWORD = "1q2w3e1!"

HUMAN_USERS = [
    ("F00001", "김민수", 0),
    ("F00002", "이서연", 1),
    ("F00003", "박준호", 1),
    ("F00004", "최유진", 2),
    ("F00005", "정하늘", 0),
    ("F00006", "오세훈", 1),
    ("F00007", "한지민", 1),
    ("F00008", "윤서아", 2),
    ("F00009", "강도윤", 0),
    ("F00010", "임채원", 2),
]


def _clear_all(db: Session) -> None:
    db.query(FavoriteEmployee).delete()
    db.query(Message).delete()
    db.query(Note).delete()
    db.query(RoomMember).delete()
    db.query(Room).delete()
    db.query(Employee).delete()
    db.query(Department).delete()
    db.commit()


def seed_database(db: Session) -> None:
    if db.query(Employee).filter(Employee.employee_id == "F00001").first():
        # Ensure One2그룹 root exists for already-seeded DBs
        root = db.query(Department).filter(Department.code == "ONE2").first()
        if not root:
            root = Department(name="One2그룹", code="ONE2", parent_id=None)
            db.add(root)
            db.flush()
            for d in db.query(Department).filter(Department.code != "ONE2").all():
                if d.parent_id is None:
                    d.parent_id = root.id
            db.commit()
        return

    # Re-seed when old E00x (or any other) demo data exists
    if db.query(Employee).first():
        _clear_all(db)

    root = Department(name="One2그룹", code="ONE2", parent_id=None)
    db.add(root)
    db.flush()

    depts = [
        Department(name="경영지원팀", code="HQ", parent_id=root.id),
        Department(name="개발팀", code="DEV", parent_id=root.id),
        Department(name="영업팀", code="SALES", parent_id=root.id),
    ]
    db.add_all(depts)
    db.flush()

    password = hash_password(SEED_PASSWORD)
    employees = [
        Employee(
            employee_id=eid,
            name=name,
            password_hash=password,
            department_id=depts[dept_idx].id,
        )
        for eid, name, dept_idx in HUMAN_USERS
    ]
    employees.append(
        Employee(
            employee_id="AI-BOT",
            name="AI 도우미",
            password_hash=hash_password("bot-disabled"),
            department_id=depts[0].id,
            is_bot=True,
        )
    )
    db.add_all(employees)
    db.flush()

    room = Room(name="전체 공지", room_type="group", created_by=employees[0].id)
    db.add(room)
    db.flush()
    for emp in employees[:10]:
        db.add(RoomMember(room_id=room.id, employee_id=emp.id))

    dm = Room(name="김민수 ↔ 이서연", room_type="direct", created_by=employees[0].id)
    db.add(dm)
    db.flush()
    db.add(RoomMember(room_id=dm.id, employee_id=employees[0].id))
    db.add(RoomMember(room_id=dm.id, employee_id=employees[1].id))

    db.commit()
