from sqlalchemy.orm import Session
from app.auth import hash_password
from app.models import Department, Employee, Room, RoomMember


def seed_database(db: Session) -> None:
    if db.query(Employee).first():
        return

    depts = [
        Department(name="경영지원팀", code="HQ"),
        Department(name="개발팀", code="DEV"),
        Department(name="영업팀", code="SALES"),
    ]
    db.add_all(depts)
    db.flush()

    password = hash_password("password123")
    employees = [
        Employee(employee_id="E001", name="김민수", password_hash=password, department_id=depts[0].id),
        Employee(employee_id="E002", name="이서연", password_hash=password, department_id=depts[1].id),
        Employee(employee_id="E003", name="박준호", password_hash=password, department_id=depts[1].id),
        Employee(employee_id="E004", name="최유진", password_hash=password, department_id=depts[2].id),
        Employee(
            employee_id="AI-BOT",
            name="AI 도우미",
            password_hash=hash_password("bot-disabled"),
            department_id=depts[0].id,
            is_bot=True,
        ),
    ]
    db.add_all(employees)
    db.flush()

    # Sample group room
    room = Room(name="전체 공지", room_type="group", created_by=employees[0].id)
    db.add(room)
    db.flush()
    for emp in employees[:4]:
        db.add(RoomMember(room_id=room.id, employee_id=emp.id))

    # Direct room between E001 and E002
    dm = Room(name="김민수 ↔ 이서연", room_type="direct", created_by=employees[0].id)
    db.add(dm)
    db.flush()
    db.add(RoomMember(room_id=dm.id, employee_id=employees[0].id))
    db.add(RoomMember(room_id=dm.id, employee_id=employees[1].id))

    db.commit()
